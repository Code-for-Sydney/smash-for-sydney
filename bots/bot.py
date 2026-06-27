import melee
import logging

class Bot(object):

    def __init__(self, character=None):
        if not character:
            character = melee.Character.JIGGLYPUFF
        self.character = character
        self.console = None
        self.port = None
        self.controller = None

        logging.info(f"Created character {self.character}")

    def create_controller(self, console, port):
        self.console = console
        self.port = port
        self.controller = melee.Controller(console=self.console, port=self.port)

    def connect(self):
        if not self.controller.connect():
            logging.error(f"ERROR: Failed to connect the controller {self.port}")
        else:
            logging.info(f"Connected controller {self.port}")

    def fight(self, gamestate):    
       pass