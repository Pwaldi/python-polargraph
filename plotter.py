#
# Python Lineart Plotter
#
# Working with Adafruit's pi-stepper
# kit. The plotter uses simple files of
# pickled lists to draw. (mono or CYMK)
# file = path or [c_path, y_path ...  ]
# path = [lines]
# lines = [vertices] (ie: [[1.,1.],[1.,2.]])
#
# pickle the path list, put in the working directory.
# and call "pl=plotter()" that's it.
#
# These lists can be made from jpg by some of the
# 'lineifiers' in the lineifiers file.
# although those operations are a matter of art
# and best done on a desktop as they are
# often prohibitively expensive for raspberry pi's.
# as implemented here.
#
# Very little is adafruit specific or hard-coded
# besides the fact that I use the 15th PWM channel
# to drive the lifter servo(s), and that the PWM
# controller is found at I2C addr 0x60
# (i2cdetect -y 1) the images directory documents
# some of the hardware build.
#
# ---------------------------------------
# Wholly authored by John Parkhill (2019)
# while on planes and shit.
# (john.parkhill@gmail.com) who retains copyright.
# John Parkhill is not liable for any consequences stemming
# from the use of this software and no gurantees are implied
# ---------------------------------------
# Distributed under Creative Commons Share-alike license.
#
from math import sqrt, pow, cos, sin, pi
import copy, pickle, time, os
import numpy as np

HAS_ADAF = True
try:
    from adafruit_motorkit import MotorKit as MK
    from adafruit_motor import stepper
    from adafruit_servokit import ServoKit as SK
except Exception as Ex:
    print("No Adafruit modules found.")
    print(Ex)
    print("I'm a mock plotter now.")
    HAS_ADAF = False

def sign(X):
    if X>0:
        return 1
    elif(X<0):
        return -1
    elif (X == 0):
        return 0
def ngon(X=0, Y=0, r=1, n=6, phase = 0):
    pts = []
    step = 2*pi/n
    for K in range(n):
        pts.append([X + r*cos(K*step+phase),
                    Y+r*sin(K*step+phase)])
    return pts
class Stepper:
    def __init__(self, ada_stepper, mock=True,
                step_delay = 0.02, step_per_rev = 200):
        self.step = ada_stepper
        self.mock = mock
        self.step_delay = step_delay
        self.step_per_rev = step_per_rev
        if (not mock):
            self.CWd = stepper.FORWARD
            self.CCWd = stepper.BACKWARD
        self.odo = 0
        self.step_pos = 0
        self.log = []
        return
    def CW(self,n=1):
        for k in range(n):
            self.odo += 1
            self.step_pos = self.odo % self.step_per_rev
            if (not self.mock):
                self.step.onestep(direction=self.CWd)
            else:
                self.log.append([time.time(), self.odo])
            time.sleep(self.step_delay)
    def CCW(self,n=1):
        for k in range(n):
            self.odo -= 1
            self.step_pos = self.odo % self.step_per_rev
            if (not self.mock):
                self.step.onestep(direction=self.CCWd)
            else:
                self.log.append([time.time(), self.odo])
            time.sleep(self.step_delay)
        return
class Lifter:
    def __init__(self, a_servo, mock=True):
        self.servo = a_servo
        self.mock = mock
        if (not self.mock):
            self.servo.actuation_range = 160
            self.servo.angle = 0
        self.log = []
        return
    def up(self):
        if not self.mock:
            self.servo.angle = 60
        else:
            self.log.append([time.time(), 60.])
        time.sleep(0.3)
        return
    def down(self):
        if not self.mock:
            self.servo.angle = 0
        else:
            self.log.append([time.time(), 0.])
        time.sleep(0.3)
        return
class Plotter:
    def __init__(self, test=True, repl=False):
        """
        All units are cm, degrees, seconds, grams
        The top of the left cog is 0,0.
        the top of the right cog is (cog_distance,0)

        Plotter must be initialized with the pen at the top,
        center of the drawable area a distance y0 from the
        from the cog-tops which should be roughly 2cm.

        The plotter adjusts lengths of left and right strings
        to achieve desired x,y. Resolution is limited
        by the cog diameters (conversely speed).
        """
        self.log = []
        self.initialize()
        print("Print area: ", self.x_lim, self.y_lim)
        print("Step Lengt: ", self.step_dl)
        print("Min Resolu: ", (self.x_lim[1]-self.x_lim[0])//self.step_dl," X ",
                           (self.y_lim[1]-self.y_lim[0])//self.step_dl)
        if (repl): 
            return
        if (test):
            self.plot_test()
        target_file = self.file_picker()
        self.plot_file(target_file)
        return
    def initialize(self, cog_distance = 91.44,
                    bottom_edge = 59.2,
                    steps_per_rev=200, cog_circum=5.*2*pi,
                    y0 = 2.
                  ):
        self.cog_distance = cog_distance
        self.steps_per_rev = 200
        self.cog_circum = cog_circum
        self.step_dl = self.cog_circum/self.steps_per_rev
        self.chain_density = 0.5 # g/cm
        self.plumb_mass = 100 # g
        self.bottom_edge = bottom_edge
        self.stepsum_L=0 # these are KEY. They give the abs. positioning
        self.stepsum_R=0
        # Pen start position.
        self.x0 = cog_distance/2.
        self.y0 = y0
        self.pad = y0
        self.x_lim = (self.pad, self.cog_distance - self.pad)
        self.y_lim = (self.pad, self.bottom_edge - self.pad)
        # 1/100th of the plottable length. Just a useful unit.
        self.cent = min(self.x_lim[1]-self.x_lim[0],
                        self.y_lim[1]-self.y_lim[0])/100.
        self.L0, self.R0 = self.xy_to_LR(self.x0,self.y0)
        self.LL = self.L0
        self.RR = self.R0
        print("Initializing I2C... ")
        if (HAS_ADAF):
            self.MK = MK()
            self.s1 = Stepper(self.MK.stepper1, mock=False)
            self.s2 = Stepper(self.MK.stepper2, mock=False)
            self.SK = SK(channels=16, address=0x60)
            self.lifter = Lifter(self.SK.servo[15], mock=False)
        else:
            self.s1 = Stepper(None)
            self.s2 = Stepper(None)
            self.lifter = Lifter(None)
        self.motor_check()
        self.init_pen()
        return
    def motor_check(self):
        self.lifter.up()
        self.s1.CW()
        self.s1.CCW()
        self.s2.CW()
        self.s2.CCW()
        self.lifter.down()
        self.lifter.up()
    def init_pen(self):
        print("Initializing pen...")
        print("Move pen to start and press ENTER.")
        _ = input()
        self.stepsum_L=0 # these are KEY. They give the abs. positioning
        self.stepsum_R=0
        self.x_now = self.x0
        self.y_now = self.y0
        self.LL = self.L0
        self.RR = self.R0
        return
    def draw_border(self):
        self.draw_rect(self.x_lim[0], self.x_lim[1], self.y_lim[0], self.y_lim[1])
        return
    def draw_rect(self, x0, x1, y0, y1):
        self.draw_vertices([[x0,y0],[x1,y0],[x1,y1],[x0,y1]], cycle=True)
    def draw_circle(self, X, Y, r = 0.5, n=20):
        verts = ngon(X, Y, r, n=20)
        self.draw_vertices(verts)
    def draw_cross(self, X,Y):
        self.draw_vertices([[X-self.cent, Y-self.cent], [X+self.cent, Y+self.cent]])
        self.draw_vertices([[X-self.cent, Y+self.cent], [X+self.cent, Y-self.cent]])
    def plot_test(self):
        self.draw_border()
        self.draw_circle(10*self.cent, 10*self.cent)
        self.draw_circle(10, 10)
        self.draw_circle(10, 40)
        self.draw_circle(40, 10)
        self.draw_circle(40, 40)
        self.draw_cross(50*self.cent, 50*self.cent)
        self.draw_cross(90*self.cent, 90*self.cent)
        # Test the path planning.
#         self.draw_paths([ngon(40, 40),
#                     ngon(40, 50),
#                     ngon(45, 55),
#                     ngon(35, 35),
#                     ngon(50, 50),
#                     ngon(50, 55),
#                     ngon(60, 55)])
    def draw_vertices(self, vertices, cycle=False):
        print("Drawing ", len(vertices), " vertices ")
        t0 = time.time()
        if (len(vertices)<2):
            return
        self.pen_up()
        self.move_to(*vertices[0])
        self.pen_down()
        for v in vertices:
            self.move_to(*v)
        if (cycle):
            self.move_to(*vertices[0])
        self.pen_up()
        print("took ", time.time()-t0, "s")
        return
    def xy_to_LR(self,x,y):
        """
        The desired L,R lengths for an
        xy coordinate.
        """
        return sqrt(x*x+y*y), sqrt(pow(self.cog_distance-x,2.0)+y*y)
    def LR_to_xy(self,L,R):
        D = self.cog_distance
        x = (L**2 - R**2 + D**2)/(2*D)
        y = sqrt(L**2 - x**2)
        return x,y
    def xy_now(self):
        return self.LR_to_xy(self.LL, self.RR)
    def log_xy(self):
        if (HAS_ADAF):
            return
        X,Y = self.xy_now()
        self.log.append([time.time(), X, Y])
    def move_to(self,x,y):
        """
        linearly interpolates by calculating required step differential
        and then interleaving the R steps as evenly as possible in the L
        """
        if (x < self.x_lim[0]):
            raise Exception("oob X")
        if (x > self.x_lim[1]):
            raise Exception("oob X")
        if (y < self.y_lim[0]):
            raise Exception("oob Y")
        if (y > self.y_lim[1]):
            raise Exception("oob Y")
        Lp, Rp = self.xy_to_LR(x,y)
        dL = Lp - self.LL
        dR = Rp - self.RR
        nL = round(abs(dL)/self.step_dl)
        nR = round(abs(dR)/self.step_dl)
        if (nL == 0 and nR == 0):
            return
        sL = sign(dL)
        sR = sign(dR)
        slope = abs(dL)//abs(dR)
        NL = 0
        NR = 0
        while NR < nR:
            self.step_R(sR)
            for k in range(int(slope)):
                if (NL < nL):
                    self.step_L(sL)
                    NL += 1
            NR += 1
        while NR < nR:
            self.step_R(sR)
            NR += 1
        while NL < nL:
            self.step_L(sL)
            NL += 1
        self.set_position()
        self.log_xy()
        return
    def step_L(self, sign):
        """
        Sign >= => the line grows.
        """
        if sign>=0:
            self.s1.CW()
        else:
            self.s1.CCW()
        self.stepsum_L += sign
        return
    def step_R(self, sign):
        if sign>=0:
            self.s2.CCW()
        else:
            self.s2.CW()
        self.stepsum_R += sign
        return
    def set_position(self):
        self.LL = self.L0+self.stepsum_L*self.step_dl
        self.RR = self.R0+self.stepsum_R*self.step_dl
    def pen_up(self):
        self.lifter.up()
        return
    def pen_down(self):
        self.lifter.down()
        return
    ###################
    # Path planning, scaling, etc.
    ###################
    def draw_paths(self, paths, n_fog = 1000):
        """
        Greedily plans paths to minimize time.
        sorts by X to begin with. Looks at
        the next n_fog
        """
        if (len(paths)<=0):
            return
        if (len(paths)<2):
            self.draw_vertices(paths[0])
            return
        paths_scheduled = [0]
        paths_remaining = [X for X in range(1,len(paths)) if len(paths[X])>2]
        print("Planning ", len(paths_remaining), " paths.")
        endpt = lambda X: paths[X][-1]
        def endpt_dist(x,y,K):
            ep = endpt(K)
            return sqrt(pow(ep[0]-x, 2.0)+pow(ep[1]-y,2.0))
        while (len(paths_remaining)>1):
            X = endpt(paths_scheduled[-1])
            distances = []
            for K in paths_remaining[:1000]:
                distances.append(endpt_dist(X[0], X[1], K))
            min_di = distances.index(min(distances))
            min_k = paths_remaining[min_di]
            paths_scheduled.append(min_k)
            paths_remaining.remove(min_k)
        paths_scheduled.append(paths_remaining.pop())
        print("drawing...")
        for K,sched in enumerate(paths_scheduled):
            print(K, "/", len(paths_scheduled))
            self.draw_vertices(paths[sched])
        return
    def path_bounds(self,path):
        A = np.array(path)
        if (len(A.shape) != 2):
            print(A.shape)
            raise Exception("Bad Path")
        if (A.shape[1]!=2):
            print(A.shape)
            raise Exception("Bad Path")
        return A.min(0).tolist()+A.max(0).tolist()
    def paths_bounds(self, paths):
        L = [self.path_bounds(X) for X in paths if len(X)>=2]
        A = np.array(L)
        return A[:,:2].min(0).tolist()+A[:,2:].max(0).tolist()
    def scale_paths(self, paths):
        """
        Fit a line drawing into the plot area. while
        preserving aspect ratio.
        TODO: auto-rotate.
        """
        cbds = self.paths_bounds(paths)
        x_dim = cbds[2]-cbds[0]
        y_dim = cbds[3]-cbds[1]
        c_paths = [(cbds[2]+cbds[0])/2., (cbds[3]+cbds[1])/2.]
        ar_paths = x_dim/y_dim
        ar_self = (self.x_lim[1]-self.x_lim[0])/(self.y_lim[1]-self.y_lim[0])
        if ar_paths < ar_self:
            # y is the limiting.
            scale_fac = .99*(self.y_lim[1]-self.y_lim[0])/y_dim
        else:
            scale_fac = .99*(self.x_lim[1]-self.x_lim[0])/x_dim
        origin_shift = np.array([[c_paths[0],c_paths[1]]])
        new_paths = []
        for p in paths:
            if (len(p)<2):
                continue
            A = (np.array(p) - origin_shift)*scale_fac + np.array([[(self.x_lim[1]+self.x_lim[0])/2, (self.y_lim[1]+self.y_lim[0])/2]])
            new_paths.append(A.tolist())
        return new_paths
    def plot_file(self, filename, border = False, scaled=True):
        with open(filename,'rb') as f:
            DATA = pickle.load(f)
        # Determine the depth.
        # CYMK is 4 X paths X pts X 2
        # B/W is paths X pts X 2
        if type(DATA[-1][0][0]) == float:
            print("Load Pen.")
            self.init_pen()
            print("Data Bounds: ", self.paths_bounds(DATA))
            if (scaled):
                print("Scaling Data....")
                SDATA = self.scale_paths(DATA)
                print("Scaled Data.", self.paths_bounds(SDATA))
                self.draw_paths(SDATA)
            else:
                self.draw_paths(DATA)
        elif len(DATA)==4:
            # TODO Scale CYMK
            print("Ploting CYMK")
            print("Load Cyan")
            self.init_pen()
            self.draw_paths(DATA[0])
            print("Load Yellow")
            self.init_pen()
            self.draw_paths(DATA[1])
            print("Load Magenta")
            self.init_pen()
            self.draw_paths(DATA[2])
            print("Load Black")
            self.init_pen()
            self.draw_paths(DATA[3])
        else:
            raise Exception("unknown data format")
    def file_picker(self, path="./"):
        files = os.listdir(path)
        print("Line Files:")
        print("----------")
        for I,f in enumerate(files):
            if f.count('.pkl')>0:
                print(I,f)
        print("----------")
        print("--- Selection ---")
        K = int(input())
        return files[K]
    def plot_paths(self):
        """
        A debug routine to simulate plotter action.
        """
        s1_path = np.array(self.s1.log)
        plt.plot(s1_path[:,0],s1_path[:,1],label="S1",alpha=0.5)
        s2_path = np.array(self.s2.log)
        plt.plot(s2_path[:,0],s2_path[:,1],label="S2",alpha=0.5)
        l_path = np.array(self.lifter.log)
        plt.plot(l_path[:,0],l_path[:,1],label="P")
        plt.legend()
        plt.title("Stepper Log")
        plt.show()
        coords = np.array(self.log)
        plt.plot(coords[:,0], coords[:,1])
        plt.title("xt")
        plt.show()
        plt.plot(coords[:,0], coords[:,2])
        plt.title("yt")
        plt.show()
        plt.plot(coords[:,1], coords[:,2])
        plt.title("Path")
        plt.show()

if __name__ == "__main__":
    pl = Plotter()
