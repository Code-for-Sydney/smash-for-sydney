from abc import ABC, abstractmethod

import melee
from melee import Character, GameState, Controller, Console

import logging

class Bot(ABC):

    def __init__(self, character: Character | None=None) -> None:
        if not character:
            character = melee.Character.MARIO
        self.character = character
        self.console: Console | None = None
        self.port: int | None = None
        self.controller: Controller | None = None

        logging.info(f"Created character {self.character}")

    def create_controller(self, console: Console, port: int):
        self.console = console
        self.port = port
        self.controller = melee.Controller(console=self.console, port=self.port)

    def connect(self):
        if not self.controller.connect():
            logging.error(f"ERROR: Failed to connect the controller {self.port}")
        else:
            logging.info(f"Connected controller {self.port}")

    @abstractmethod
    def fight(self, gamestate: GameState):    
       ...