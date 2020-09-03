#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2016 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import logging
log = logging.getLogger('')
log.addHandler(logging.NullHandler())

import sys
sys.modules['cloudpickle'] = None
import random
import tempfile
import pyqtgraph as pg
from time import sleep
import numpy as np
import pyvisa

from pymeasure.instruments.srs import SR830
from pymeasure.instruments.signalrecovery import DSP7265
from pymeasure.instruments.sorensen import Sorensen30035E
from pymeasure.instruments.lakeshore import LakeShore331
from pymeasure.instruments.keithley import Keithley2400
from pymeasure.instruments import Instrument
from pymeasure.log import console_log
from pymeasure.experiment import Results
from pymeasure.display.Qt import QtGui, fromUi
from pymeasure.display.windows import ManagedWindow
from pymeasure.experiment import Procedure, IntegerParameter, Parameter, FloatParameter, BooleanParameter, Parameter
from pymeasure.experiment import unique_filename


class MagFieldProcedure(Procedure):

    #Magnetic Field calibration (input field, get current)

    pA = -6.78951587e-06       #Constant
    pB = 3.27549922e-03       #First order term
    
    def IfromB(self,B):
        if B < 0:
            return 0
        elif B >= self.pA:
            return self.pA + (B)*self.pB + (B*B)*self.pC + (B*B*B)*self.pD #Calculating the current to produce a given H
        else:
            return 0.0

    fileroot = Parameter('File Root',default='.')
    filename = Parameter('File Prepend',default='2ndHarm')
    field = FloatParameter('Applied Field', units='T', default=.1)
    lockinamp = FloatParameter('Lockin Amplitude', units='V', default = 1.0)
    lockinfreq = FloatParameter('Lockin Reference', units='Hz', default = 1337.7)
    start_angle = FloatParameter('Start Angle', units='degrees', default=0)
    stop_angle = FloatParameter('Stop Angle', units='degrees', default=270)
    angle_step = FloatParameter('Angle Step', units='degrees', default=1)
    delay = FloatParameter('Delay Time', units='ms', default=100)

    inverse_spacing = BooleanParameter('Inverse Spacing')
    field_start = FloatParameter('Start Field', units='T', default=.05)
    field_stop = FloatParameter('Stop Field', units='T', default=.3)
    field_steps = IntegerParameter('Field Steps', default=10)

    shutdown_after = BooleanParameter('Shutdown Field After?')


    

    DATA_COLUMNS = ['Angle (deg)','Current (A)', 'Magnetic Field (T)',
     '1X Voltage (V)', '1Y Voltage (V)',
     '2X Voltage (V)', '2Y Voltage (V)']

    def inmotion(self,rotator):
        moving = -1
        success = False
        while not success:
            try:
                moving=int(rotator.query('LOC?'))
            except pyvisa.VisaIOError:
                pass
            except ValueError:
                moving = 0
                success = True
            else:
                success = True
                if moving > -1:
                    moving = 0
                else:
                    moving = -1
            sleep(0.1)
        return moving


    def homeangle(self, rotator):
        success = False
        while not success:
            try:
                rotator.write('HOME')
            except pyvisa.VisaIOError:
                pass
            else:
                success = True
        moving = -1
        while moving ==-1:
            moving = self.inmotion(self.rotator)
            sleep(1)

    def setangle(self, rotator,angle):
        success = False
        while not success:
            try:
                rotator.write('GOTO %f' % angle)
            except pyvisa.VisaIOError:
                pass
            else:
                success = True

    def getangle(self, rotator):
        moving = -1
        while moving == -1:
            moving = self.inmotion(rotator)
            sleep(0.1)

        success = False
        while not success:
            try:
                angle = float(rotator.query('LOC?'))
            except pyvisa.VisaIOError:
                pass
            except ValueError:
                pass
            else:
                success = True
            sleep(0.1)
        return angle



    def startup(self):
        log.info("Setting up instruments")
        self.source = Sorensen30035E(7)

        self.lockin1 = DSP7265(27)
        self.lockin2 = DSP7265(12)


        self.rm = pyvisa.ResourceManager()
        self.rotator = self.rm.open_resource('ASRL4::INSTR')
        sleep(2)
        self.rotator.clear()
        sleep(1)
        self.homeangle(self.rotator)


    def execute(self):
        #Defining the current values
        angles_up = np.arange(self.start_angle, self.stop_angle+self.angle_step, self.angle_step)
        steps_up = len(angles_up)

        ###Ramping up the magnet current to minimum current
        log.info("Ramping to field value.")
        self.current = self.IfromB(self.field)
        if self.current > 0 :
            self.source.ramp_to_current(self.current, self.current/1e-1)
        self.source.ramp_to_current(self.current)
        sleep(1)

        log.info('Setting Lockin Parameters')
        self.lockin1.voltage = self.lockinamp
        self.lockin1.frequency = self.lockinfreq

        log.info("Starting to sweep through angle.")
        for i, angle in enumerate(angles_up):
            log.debug("Setting angle: %g degrees" % angle)
            self.setangle(self.rotator,angle)
            true_angle = self.getangle(self.rotator)
            sleep(self.delay*1e-3)
            magfield = self.field
            lockinX1 = self.lockin1.x
            lockinY1 = self.lockin1.y
            lockinX2 = self.lockin2.x
            lockinY2 = self.lockin2.y
            data = {
                'Angle (deg)' : true_angle,
                'Current (A)': self.current,
                'Magnetic Field (T)': magfield,
                '1X Voltage (V)': lockinX1,
                '1Y Voltage (V)': lockinY1,
                '2X Voltage (V)': lockinX1,
                '2Y Voltage (V)': lockinY1,,
            }
            self.emit('results', data)
            self.emit('progress', 100.*i/steps_up)
            if self.should_stop():
                log.warning("Catch stop command in procedure")
                return


    def shutdown(self):
        log.info("Shutting down.")

        #Ramping down the magnetic field
        if self.shutdown_after:
            now = self.current
            self.source.ramp_to_current(0.0,now/1e-1)
            sleep(1)
        sleep(1)
        self.rotator.close()
        #Turning off the RF source
        #self.RFsource.power = -100
        log.info("Finished")


class MainWindow(ManagedWindow):

    def __init__(self):
        super(MainWindow, self).__init__(
            procedure_class=MagFieldProcedure,
            inputs=['fileroot','filename','field',
            'lockinamp','lockinfreq',
            'start_angle','stop_angle','angle_step','delay',
            'inverse_spacing','field_start','field_stop','field_steps',
            'shutdown_after'],
            displays=[
                'field','delay', 'lockinamp','angle_step', 'start_angle', 'stop_angle', 
                'lockinfreq'],
            x_axis='Angle (deg)',
            y_axis='1Y Voltage (V)'
        )
        self.setWindowTitle('ST-FMR Kavli Lab')


    def queue(self):
        
        procedure = self.make_procedure()

        directory = procedure.fileroot
        

        if procedure.inverse_spacing:
            fields = np.linspace(1/procedure.field_start,1/procedure.field_stop,procedure.field_steps)
            fields = 1/fields
            for field in fields:
                filename = unique_filename(directory, prefix=procedure.filename, ext='txt', datetimeformat='')
                procedure.field = field
                results = Results(procedure, filename)
                experiment = self.new_experiment(results)

                self.manager.queue(experiment)

        else:
            filename = unique_filename(directory, prefix=procedure.filename, ext='txt', datetimeformat='')

            results = Results(procedure, filename)
            experiment = self.new_experiment(results)

            self.manager.queue(experiment)


if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())