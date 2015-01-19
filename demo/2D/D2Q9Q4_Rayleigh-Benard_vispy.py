"""
Resolution of the system Navier-Stokes + heat equations

d_t(u) + u . d_x(u) = - d_x(p) + Pr d_xx(u) + Ra Pr T g
d_x.(u) = 0
d_t(T) + u . d_x(T) = d_xx(T)

g = (0, -1)

The system is rewritten in the compressible form in order to use
a D2Q9 scheme for the Navier-Stokes
and
a D2Q4 scheme for the convection-diffusion equation
"""
import sys

import cmath
from math import pi, sqrt
import numpy as np
import sympy as sp
from sympy.matrices import Matrix, zeros
import mpi4py.MPI as mpi
import time

import pyLBM
from pyLBM.elements import *
import pyLBM.geometry as pyLBMGeom
import pyLBM.stencil as pyLBMSten
import pyLBM.domain as pyLBMDom
import pyLBM.scheme as pyLBMScheme
import pyLBM.simulation as pyLBMSimu
import pyLBM.boundary as pyLBMBound
import pyLBM.generator as pyLBMGen

import numba

from vispy import gloo
from vispy import app
from vispy.gloo import gl
from vispy.util.transforms import ortho

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cm

VERT_SHADER = """
// Uniforms
uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_projection;
uniform float u_antialias;

// Attributes
attribute vec2 a_position;
attribute vec2 a_texcoord;

// Varyings
varying vec2 v_texcoord;

// Main
void main (void)
{
    v_texcoord = a_texcoord;
    gl_Position = u_projection * vec4(a_position,0.0,1.0);
}
"""

FRAG_SHADER = """
uniform sampler2D u_texture;
varying vec2 v_texcoord;
void main()
{
    // Color
    float c = texture2D(u_texture, v_texcoord).r;
    gl_FragColor = vec4(c, 0., 1.-c, 1.);
    
    // Gray
    //gl_FragColor = texture2D(u_texture, v_texcoord);
    //gl_FragColor.a = 1.0;
}
"""

class Canvas(app.Canvas):

    def __init__(self, dico):
        coeff = 2
        self.sol = pyLBMSimu.Simulation(dico)
        self.indout = np.where(self.sol.domain.in_or_out == self.sol.domain.valout)
        W, H = self.sol.m[0].shape[1:]
        W -= 2
        H -= 2
        self.W, self.H = W, H
        # A simple texture quad
        self.data = np.zeros(4, dtype=[ ('a_position', np.float32, 2),
                                        ('a_texcoord', np.float32, 2) ])
        self.data['a_position'] = np.array([[0, 0], [coeff * W, 0], [0, coeff * H], [coeff * W, coeff * H]])
        self.data['a_texcoord'] = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
        app.Canvas.__init__(self, close_keys='escape')
        self.title = "Solution t={0:f}".format(0.)
        self.min, self.max = -dtheta, dtheta
        self.ccc = 1./(self.max-self.min)
        self.size = W * coeff, H * coeff
        self.program = gloo.Program(VERT_SHADER, FRAG_SHADER)
        self.texture = gloo.Texture2D(self.ccc*(self.sol.m[1][0,:,:].astype(np.float32) - self.min))
        self.texture.interpolation = gl.GL_LINEAR

        self.program['u_texture'] = self.texture
        self.program.bind(gloo.VertexBuffer(self.data))

        self.projection = np.eye(4, dtype=np.float32)
        self.projection = ortho(0, W, 0, H, -1, 1)
        self.program['u_projection'] = self.projection

        self.timer = app.Timer(self.sol.dt)
        self.timer.connect(self.on_timer)

    def on_initialize(self, event):
        gl.glClearColor(1,1,1,1)

    def on_resize(self, event):
        width, height = event.size
        gl.glViewport(0, 0, width, height)
        self.projection = ortho(0, width, 0, height, -100, 100)
        self.program['u_projection'] = self.projection

        W, H = self.W, self.H
        # Compute the new size of the quad
        r = width / float(height)
        R = W / float(H)
        if r < R:
            w, h = width, width / R
            x, y = 0, int((height - h) / 2)
        else:
            w, h = height * R, height
            x, y = int((width - w) / 2), 0
        self.data['a_position'] = np.array(
            [[x, y], [x + w, y], [x, y + h], [x + w, y + h]])
        self.program.bind(gloo.VertexBuffer(self.data))

    def on_draw(self, event):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        self.program.draw(gl.GL_TRIANGLE_STRIP)

    def on_key_press(self, event):
        if event.text == ' ':
            if self.timer.running:
                self.timer.stop()
            else:
                self.timer.start()
        if event.text == 'n':
            self.go_on()
            self.maj()

    def on_timer(self, event):
        self.go_on()
        #print "Max velocity : {0:10.3e} {1:10.3e}\n".format(np.max(self.sol.m[0][1,:,:]), np.max(self.sol.m[0][2,:,:]))
        self.maj()

    def go_on(self):
        for k in xrange(10):
            self.sol.scheme.m2f(self.sol.m, self.sol.F)
            self.sol.scheme.set_boundary_conditions(self.sol.F, self.sol.m, self.sol.bc)
            self.sol.scheme.transport(self.sol.F)
            self.sol.scheme.f2m(self.sol.F, self.sol.m)
            self.sol.m[0][2,:,:] += 0.5 * self.sol.dt * Ra * Pr * self.sol.m[1][0,:,:]
            self.sol.scheme.relaxation(self.sol.m)
            self.sol.m[0][2,:,:] += 0.5 * self.sol.dt * Ra * Pr * self.sol.m[1][0,:,:]
            self.sol.t += self.sol.dt

    def maj(self):
        self.title = "Solution t={0:f}".format(self.sol.t)
        dummy = self.ccc*(self.sol.m[1][0,:,:].astype(np.float32) - self.min)
        dummy[self.indout[1], self.indout[0]] = 0.
        self.texture.set_data(dummy.astype(np.float32))
        self.update()        

X, Y, Z, LA = sp.symbols('X,Y,Z,LA')

u = [[sp.Symbol("m[%d][%d]"%(i,j)) for j in xrange(25)] for i in xrange(10)]

def initialization_rho(x,y):
    return rhoo * np.ones((x.shape[0], y.shape[0]), dtype='float64')

def initialization_qx(x,y):
    return np.zeros((x.shape[0], y.shape[0]), dtype='float64')

def initialization_qy(x,y):
    return np.zeros((x.shape[0], y.shape[0]), dtype='float64')

def initialization_T(x,y):
    #return np.zeros((x.shape[0], y.shape[0]), dtype='float64') - 2 * (x-0.5*(xmax+xmin))/(xmax-xmin) * dtheta
    #return np.zeros((x.shape[0], y.shape[0]), dtype='float64') - 2 * (y-0.5*(ymax+ymin))/(ymax-ymin) * dtheta
    return -dtheta * np.ones((x.shape[0], y.shape[0]), dtype='float64')

def bc_right(f, m, x, y, scheme):
    m[0][0] = 0.
    m[0][1] = 0.
    m[0][2] = 0.
    m[1][0] = -dtheta
    scheme.equilibrium(m)
    scheme.m2f(m, f)

def bc_left(f, m, x, y, scheme):
    m[0][0] = 0.
    m[0][1] = 0.
    m[0][2] = 0.
    m[1][0] = dtheta
    scheme.equilibrium(m)
    scheme.m2f(m, f)

def bc_up(f, m, x, y, scheme):
    m[0][0] = 0.
    m[0][1] = 0.
    m[0][2] = 0.
    m[1][0] = -dtheta
    scheme.equilibrium(m)
    scheme.m2f(m, f)

def bc_down(f, m, x, y, scheme):
    m[0][0] = 0.
    m[0][1] = 0.
    m[0][2] = 0.
    m[1][0] = dtheta * (1. + 1./100 * np.random.random_sample(x.shape))# + 8*dtheta*(x-xmin)*(xmax-x)/(xmax-xmin)**2
    scheme.equilibrium(m)
    scheme.m2f(m, f)

def plot(sol):
    plt.clf()
    plt.imshow(np.float32(sol.m[1][0].transpose()), origin='lower', cmap=cm.gray)
    plt.title('temperature at t = {0:f}'.format(sol.t))
    plt.draw()
    plt.pause(1.e-3)

if __name__ == "__main__":
    # parameters
    Pr = 0.71e-2
    Ra = 2.e4
    dim = 2 # spatial dimension
    xmin, xmax, ymin, ymax = 0., 2., 0., 1
    dx = 1./256 # spatial step
    la = 20. # velocity of the scheme
    rhoo = 1.
    thetao = 0.
    dtheta = 0.5
    # parameters of the D2Q9 scheme
    mu   = Pr
    zeta = 10*mu
    dummy = 3./(la*rhoo*dx)
    s3 = 1./(0.5+zeta*dummy)
    s4 = s3
    s5 = s4
    s6 = s4
    s7 = 1.0/(0.5+mu*dummy)
    s8 = s7
    sD2Q9  = [0.,0.,0.,s3,s4,s5,s6,s7,s8]
    dummy = 1./(LA**2*rhoo)
    qx2 = dummy*u[0][1]**2
    qy2 = dummy*u[0][2]**2
    q2  = qx2+qy2
    qxy = dummy*u[0][1]*u[0][2]
    vitessesD2Q9 = range(9)
    polynomesD2Q9 = Matrix([1,
                            LA*X, LA*Y,
                            3*(X**2+Y**2)-4,
                            0.5*(9*(X**2+Y**2)**2-21*(X**2+Y**2)+8),
                            3*X*(X**2+Y**2)-5*X, 3*Y*(X**2+Y**2)-5*Y,
                            X**2-Y**2, X*Y]
        )
    equilibresD2Q9 = Matrix([u[0][0],
                             u[0][1], u[0][2],
                             -2*u[0][0] + 3*q2,
                             u[0][0]+1.5*q2,
                             -u[0][1]/LA, -u[0][2]/LA,
                             qx2-qy2, qxy]
        )
    # parameters of the D2Q4 scheme
    kappa = 1.e-2
    sigma_qx = 2*kappa/la/dx
    sigma_xy = 10*sigma_qx
    s_qx = 1./(0.5+sigma_qx)
    s_xy = 1./(0.5+sigma_xy)
    sD2Q4  = [0., s_qx, s_qx, s_xy]
    vitessesD2Q4 = range(1,5)
    polynomesD2Q4 = Matrix([1, LA*X, LA*Y, X**2-Y**2])
    equilibresD2Q4 = Matrix([u[1][0], u[0][1]*u[1][0], u[0][2]*u[1][0], 0.])

    dico = {
        'box':{'x':[xmin, xmax], 'y':[ymin, ymax], 'label':[1, -1, 2, -1]},
        'space_step':dx,
        'number_of_schemes':2,
        'scheme_velocity':la,
        0:{'velocities':range(9),
           'polynomials':polynomesD2Q9,
            'relaxation_parameters':sD2Q9,
            'equilibrium':equilibresD2Q9,
        },
        1:{'velocities':vitessesD2Q4,
           'polynomials':polynomesD2Q4,
           'relaxation_parameters':sD2Q4,
           'equilibrium':equilibresD2Q4,
        },
        'init':{'type':'moments',
                0:{0:(initialization_rho,),
                   1:(initialization_qx,),
                   2:(initialization_qy,)
                },
                1:{0:(initialization_T,)}
        },
        'boundary_conditions':{
            0:{'method':{0: pyLBMBound.bouzidi_bounce_back, 1: pyLBMBound.bouzidi_bounce_back}, 'value':None},
            1:{'method':{0: pyLBMBound.bouzidi_bounce_back, 1: pyLBMBound.bouzidi_anti_bounce_back}, 'value':bc_down},
            2:{'method':{0: pyLBMBound.bouzidi_bounce_back, 1: pyLBMBound.bouzidi_anti_bounce_back}, 'value':bc_up},
        },
        'generator': pyLBMGen.CythonGenerator,
    }

    print "Prandt number {0:10.3e}".format(Pr)
    print "Rayleigh number {0:10.3e}".format(Ra)

    c = Canvas(dico)
    c.show()
    app.run()
    