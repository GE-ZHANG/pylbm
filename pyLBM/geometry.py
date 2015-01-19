# Authors:
#     Loic Gouarin <loic.gouarin@math.u-psud.fr>
#     Benjamin Graille <benjamin.graille@math.u-psud.fr>
#
# License: BSD 3 clause

import sys
import logging
from math import sin, cos
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cm
from matplotlib.patches import Ellipse, Polygon

import mpi4py.MPI as mpi

from .elements import *

from .logs import setLogger, compute_lvl
#log = setLogger(__name__)

def get_box(dico, log = None):
    """
    return the dimension and the bounds of the box defined in the dictionnary.

    Parameters
    ----------
    dico : a dictionnary

    Returns
    -------
    dim : the dimension of the box
    bounds: the bounds of the box

    """
    try:
        box = dico['box']
        try:
            bounds = [box['x']]
            dim = 1
            boxy = box.get('y', None)
            if boxy is not None:
                bounds.append(boxy)
                dim += 1
                boxz = box.get('z', None)
                if boxz is not None:
                    bounds.append(boxz)
                    dim += 1
        except KeyError:
            if log is not None:
                log.error("'x' interval not found in the box definition of the geometry.")
            sys.exit()
    except KeyError:
        if log is not None:
            log.error("'box' key not found in the geometry definition. Check the input dictionnary.")
        sys.exit()
    return dim, bounds

class Geometry:
    """
    Create a geometry that defines the fluid part and the solid part.

    Parameters
    ----------
    dico : a dictionary that contains the following `key:value`

        box : a dictionary that contains the following `key:value`
            x : a list of the bounds in the first direction
            y : a list of the bounds in the second direction (optional)
            z : a list of the bounds in the third direction (optional)
            label : an integer or a list of integers (length twice the number of dimensions)
                used to label each edge

        elements : TODO .....................

    Attributes
    ----------
    dim : number of spatial dimensions (example: 1, 2, or 3)
    bounds : a list that contains the bounds of the box ((x[0]min,x[0]max),...,(x[dim-1]min,x[dim-1]max))
    bounds_tag : a dictionary that contains the tag of all the bounds and the description
    list_elem : a list that contains each element added or deleted in the box
    # (to remove) list_label : a list that contains the label of each border

    Members
    -------
    add_elem : function that adds an element in the box
    visualize : function to visualize the box

    Examples
    --------
    see demo/examples/geometry/*.py

    """

    def __init__(self, dico):
        self.lvl = compute_lvl(dico.get('logs', None))
        self.log = setLogger(__name__, lvl = self.lvl)
        self.dim, self.bounds = get_box(dico, self.log)

        # mpi support
        comm = mpi.COMM_WORLD
        size = comm.Get_size()
        split = mpi.Compute_dims(size, self.dim)

        self.bounds = np.asarray(self.bounds, dtype='f8')
        t = (self.bounds[:, 1] - self.bounds[:, 0])/split
        self.comm = comm.Create_cart(split, (True,)*self.dim)
        rank = self.comm.Get_rank()
        coords = self.comm.Get_coords(rank)
        coords = np.asarray(coords)
        self.bounds[:, 1] = self.bounds[:, 0] + t*(coords + 1)
        self.bounds[:, 0] = self.bounds[:, 0] + t*coords


        self.isInterface = [False]*2*self.dim
        for i in xrange(self.dim):
            voisins = self.comm.Shift(i, 1)
            if voisins[0] != rank:
                self.isInterface[i*2] = True
            if voisins[1] != rank:
                self.isInterface[i*2 + 1] = True

        self.log.debug("Message from geometry.py (isInterface):\n {0}".format(self.isInterface))

        self.list_elem = []

        try:
            dummylab = dico['box']['label']
        except:
            dummylab = 0
        if isinstance(dummylab, int):
            #self.list_label.append([dummylab]*2*self.dim)
            self.box_label = [dummylab]*2*self.dim
        else:
            #self.list_label.append([loclab for loclab in dummylab])
            self.box_label = [loclab for loclab in dummylab]

        elem = dico.get('elements', None)
        if elem is not None:
            for elemk in elem:
                self.list_elem.append(elemk)
        self.log.debug(self.__str__())


    def __str__(self):
        s = "Geometry informations\n"
        s += "\t spatial dimension: {0:d}\n".format(self.dim)
        s += "\t bounds of the box: \n" + self.bounds.__str__() + "\n"
        if (len(self.list_elem) != 0):
            s += "\t List of elements added or deleted in the box\n"
            for k in xrange(len(self.list_elem)):
                s += "\t\t Element number {0:d}: ".format(k) + self.list_elem[k].__str__() + "\n"
        return s

    def add_elem(self, elem):
        """
        add a solid or a fluid part in the domain.

        Parameters
        ----------
        elem : form of the part to add (or to del)

        Examples
        --------

        """

        self.list_elem.append(elem)

    def visualize(self, viewlabel=False):
        plein = 'blue'
        fig = plt.figure(0,figsize=(8, 8))
        fig.clf()
        plt.ion()
        plt.hold(True)
        ax = fig.add_subplot(111)
        if (self.dim == 1):
            xmin = (float)(self.bounds[0][0])
            xmax = (float)(self.bounds[0][1])
            L = xmax-xmin
            h = L/20
            l = L/50
            plt.plot([xmin+l,xmin,xmin,xmin+l],[-h,-h,h,h],plein,lw=5)
            plt.plot([xmax-l,xmax,xmax,xmax-l],[-h,-h,h,h],plein,lw=5)
            plt.plot([xmin,xmax],[0.,0.],plein,lw=5)
            if viewlabel:
                plt.text(xmax-l, -2*h, self.box_label[0], fontsize=18, horizontalalignment='center',verticalalignment='center')
                plt.text(xmin+l, -2*h, self.box_label[1], fontsize=18, horizontalalignment='center',verticalalignment='center')
            plt.axis('equal')
        elif (self.dim == 2):
            xmin = (float)(self.bounds[0][0])
            xmax = (float)(self.bounds[0][1])
            ymin = (float)(self.bounds[1][0])
            ymax = (float)(self.bounds[1][1])
            plt.fill([xmin,xmax,xmax,xmin], [ymin,ymin,ymax,ymax], fill=True, color=plein)
            if viewlabel:
                plt.text(0.5*(xmin+xmax), ymin, self.box_label[0], fontsize=18, horizontalalignment='center',verticalalignment='bottom')
                plt.text(xmax, 0.5*(ymin+ymax), self.box_label[1], fontsize=18, horizontalalignment='right',verticalalignment='center')
                plt.text(0.5*(xmin+xmax), ymax, self.box_label[2], fontsize=18, horizontalalignment='center',verticalalignment='top')
                plt.text(xmin, 0.5*(ymin+ymax), self.box_label[3], fontsize=18, horizontalalignment='left',verticalalignment='center')
            plt.axis([xmin, xmax, ymin, ymax])
            comptelem = 0
            for elem in self.list_elem:
                if elem.isfluid:
                    coul = plein
                else:
                    coul = 'white'
                elem._visualize(ax, coul, viewlabel)
        plt.title("Geometry",fontsize=14)
        plt.draw()
        plt.hold(False)
        plt.ioff()
        plt.show()

    def list_of_labels(self):
        """
           return the list of all the labels used in the geometry
        """
        L = np.array(self.box_label, dtype=np.int32)
        for elem in self.list_elem:
            L = np.union1d(L, elem.label)
        #for l in self.list_label:
        #    L = np.union1d(L, l)
        return L


def test_1D(number):
    """
    Test 1D-Geometry

    * ``Test_1D(0)`` for the segment (0,1)
    * ``Test_1D(1)`` for the segment (-1,2)
    """
    if number == 0:
        dgeom = {'box':{'x': [0, 1]}}
    elif number == 1:
        dgeom = {'box':{'x': [-1, 2]}}
    else:
        dgeom = None

    if dgeom is not None:
        geom = Geometry(dgeom)
        print "\n\nTest number {0:d} in {1:d}D:".format(number, geom.dim)
        print geom
        geom.visualize()
        return 1
    else:
        return 0

def test_2D(number):
    """
    Test 2D-Geometry

    * ``Test_2D(0)`` for the square [0,1]**2
    * ``Test_2D(1)`` for the rectangular cavity with a circular obstacle
    * ``Test_2D(2)`` for the circular cavity
    * ``Test_2D(3)`` for the square cavity with a triangular obstacle
    """
    if number == 0:
        dgeom = {'box':{'x': [0, 1], 'y': [0, 1]}}
    elif number == 1:
        dgeom = {'box':{'x': [0, 2], 'y': [0, 1]},
                 'elements':[Circle((0.5, 0.5), 0.1)]
                }
    elif number == 2:
        dgeom = {'box':{'x': [0, 2], 'y': [0, 1]},
                 'elements':[Parallelogram((0, 0), (2, 0), (0, 1)),
                             Parallelogram((0, .4), (2, 0), (0, .2), isfluid=True),
                             Circle((1, .5), 0.5, isfluid=True),
                             Circle((1, .5), 0.2, isfluid=False)
                             ]
                }
    elif number == 3:
        dgeom = {'box':{'x': [0, 1], 'y': [0, 1]},
                 'elements':[Triangle((0.3, 0.3), (0.5, -0.1), (0.3, 0.5))]}
    elif (number==4):
        dgeom = {'box':{'x': [0, 2], 'y': [0, 1]},
                 'elements':[Parallelogram((0.4, 0.4), (0., 0.2), (0.2, 0.)),
                             Parallelogram((1.4, 0.5), (0.1, 0.1), (0.1, -0.1))
                            ]
                }
    else:
        dgeom = None
    if dgeom is not None:
        geom = Geometry(dgeom)
        print "\n\nTest number {0:d} in {1:d}D:".format(number, geom.dim)
        print geom
        geom.visualize()
        return 1
    else:
        return 0

if __name__ == "__main__":
    k = 1
    compt = 0
    while k==1:
        k = test_1D(compt)
        compt += 1
    k = 1
    compt = 2
    while (k==1):
        k = test_2D(compt)
        compt += 1