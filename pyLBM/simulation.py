# Authors:
#     Loic Gouarin <loic.gouarin@math.u-psud.fr>
#     Benjamin Graille <benjamin.graille@math.u-psud.fr>
#
# License: BSD 3 clause

import sys
import cmath
import numpy as np
import sympy as sp
from sympy.matrices import Matrix, zeros
import mpi4py.MPI as mpi
import time

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cm

from .domain import Domain
from .scheme import Scheme
from .geometry import Geometry
from .stencil import Stencil
from .boundary import Boundary

from pyLBM import utils

from .logs import setLogger, compute_lvl

X, Y, Z, LA = sp.symbols('X,Y,Z,LA')
u = [[sp.Symbol("m[%d][%d]"%(i,j)) for j in xrange(25)] for i in xrange(10)]

class Simulation:
    """
    Simulation class

    * Arguments ####### A REPRENDRE

        - Domain: object of class :py:class:`LBMpy.Domain.Domain`
        - Scheme: object of class :py:class:`LBMpy.Scheme.Scheme`
        - type:   optional argument (default value is 'float64')

    * Attributs

        - dim:        spatial dimension
        - type:       the type of the values
        - Domain:     the Domain given in argument
        - Scheme:     the Scheme given in argument
        - m:          a numpy array that contains the values of the moments in each point
        - F:          a numpy array that contains the values of the distribution functions in each point

    """
    def __init__(self, dico, domain=None, scheme=None, type='float64', nv_on_beg=True):
        self.type = type
        self.order = 'C'

        self.lvl = compute_lvl(dico.get('logs', None))
        log = setLogger(__name__, lvl = self.lvl)

        try:
            if domain is not None:
                self.domain = domain
            else:
                self.domain = Domain(dico)
        except KeyError:
            print 'Error in the creation of the domain: wrong dictionnary'
            sys.exit()

        try:
            if scheme is not None:
                self.scheme = scheme
            else:
                self.scheme = Scheme(dico, nv_on_beg=nv_on_beg)
        except KeyError:
            print 'Error in the creation of the scheme: wrong dictionnary'
            sys.exit()

        self.t = 0.
        self.nt = 0
        self.dt = self.domain.dx / self.scheme.la
        try:
            assert self.domain.dim == self.scheme.dim
        except:
            print 'Solution: the dimension of the domain and of the scheme are not the same\n'
            sys.exit()

        self.dim = self.domain.dim

        #self.nv_on_beg = nv_on_beg
        self.nv_on_beg = self.scheme.nv_on_beg

        if self.nv_on_beg:
            msize = [self.scheme.stencil.nv_ptr[-1]] + self.domain.Na[::-1]
            self._m = np.empty(msize, dtype=self.type, order=self.order)
            self._F = np.empty(msize, dtype=self.type, order=self.order)
        else:
            msize = self.domain.Na[::-1] + [self.scheme.stencil.nv_ptr[-1]]
            self._m = np.empty(msize, dtype=self.type, order=self.order)
            self._F = np.empty(msize, dtype=self.type, order=self.order)
            self._Fold = np.empty(msize, dtype=self.type, order=self.order)

        # self.m = [np.empty([self.scheme.stencil.nv[k]] + self.domain.Na, dtype=self.type, order=self.order) for k in range(self.scheme.nscheme)]
        # self.F = [np.empty([self.scheme.stencil.nv[k]] + self.domain.Na, dtype=self.type, order=self.order) for k in range(self.scheme.nscheme)]

        self.bc = Boundary(self.domain, dico)
        self.initialization(dico)

    @utils.item2property
    def m(self, i, j):
        if type(j) is slice:
            jstart, jstop = j.start, j.stop
            if j.start is None:
                jstart = 0
            if j.stop is None:
                jstop = self.scheme.stencil.nv[i] - 1
            jj = slice(self.scheme.stencil.nv_ptr[i] + jstart,
                       self.scheme.stencil.nv_ptr[i] + jstop)
            if self.nv_on_beg:
                return self._m[jj]
            else:
                return self._m[:, :, jj]
        if self.nv_on_beg:
            return self._m[self.scheme.stencil.nv_ptr[i] + j]
        else:
            return self._m[:, :, self.scheme.stencil.nv_ptr[i] + j]

    @m.setter
    def m(self, i, j, value):
        if self.nv_on_beg:
            self._m[self.scheme.stencil.nv_ptr[i] + j] = value
        else:
            self._m[:, :, self.scheme.stencil.nv_ptr[i] + j] = value

    @utils.item2property
    def F(self, i, j):
        if self.nv_on_beg:
            return self._F[self.scheme.stencil.nv_ptr[i] + j]
        else:
            return self._F[:, :, self.scheme.stencil.nv_ptr[i] + j]

    @F.setter
    def F(self, i, j, value):
        if self.nv_on_beg:
            self._F[self.scheme.stencil.nv_ptr[i] + j] = value
        else:
            self._F[:, :, self.scheme.stencil.nv_ptr[i] + j] = value

    def __str__(self):
        s = "Simulation informations\n"
        s += self.domain.__str__()
        s += self.scheme.__str__()
        return s

    def initialization(self, dico):
        inittype = dico['inittype']
        if self.dim == 1:
            x = self.domain.x[0]
            coords = (x,)
        elif self.dim == 2:
            x = self.domain.x[0][:,np.newaxis]
            y = self.domain.x[1][np.newaxis, :]
            coords = (x, y)

        schemes = dico['schemes']
        for ns, s in enumerate(schemes):
            for k, v in s['init'].iteritems():
                f = v[0]
                extraargs = v[1] if len(v) == 2 else ()
                fargs = coords + extraargs
                if inittype == 'moments':
                    if self.nv_on_beg:
                        self._m[self.scheme.stencil.nv_ptr[ns] + k] = f(*fargs)
                    else:
                        self._m[:, :, self.scheme.stencil.nv_ptr[ns] + k] = f(*fargs)
                else:
                    if self.nv_on_beg:
                        self._F[self.scheme.stencil.nv_ptr[ns] + k] = f(*fargs)
                    else:
                        self._F[:, :, self.scheme.stencil.nv_ptr[ns] + k] = f(*fargs)

        if inittype == 'moments':
            self.scheme.equilibrium(self._m)
            self.scheme.m2f(self._m, self._F)
        else:
            self.scheme.f2m(self._F, self._m)

        if not self.nv_on_beg:
            self._Fold[:] = self._F[:]

    def one_time_step(self):
        self.scheme.set_boundary_conditions(self._F, self._m, self.bc, self.nv_on_beg)

        if self.nv_on_beg:
            self.scheme.transport(self._F)
            self.scheme.f2m(self._F, self._m)
            self.scheme.relaxation(self._m)
            self.scheme.m2f(self._m, self._F)
        else:
            self._Fold[:] = self._F[:]
            self.scheme.onetimestep(self._m, self._F, self._Fold, self.domain.in_or_out, self.domain.valin)
            ftmp = self._Fold
            self._Fold = self._F
            self._F = ftmp

        self.t += self.dt
        self.nt += 1

    def affiche_2D(self):
        fig = plt.figure(0,figsize=(8, 8))
        fig.clf()
        plt.ion()
        plt.imshow(np.float32(self.m[0][0][1:-1,1:-1].transpose()), origin='lower', cmap=cm.gray, interpolation='nearest')
        plt.title("Solution",fontsize=14)
        plt.draw()
        plt.hold(False)
        plt.ioff()
        plt.show()

    def affiche_1D(self):
        fig = plt.figure(0,figsize=(8, 8))
        fig.clf()
        plt.ion()
        plt.plot(self.domain.x[0][1:-1],self.m[0][0][1:-1])
        plt.title("Solution",fontsize=14)
        plt.draw()
        plt.hold(False)
        plt.ioff()
        #plt.show()

if __name__ == "__main__":
    pass