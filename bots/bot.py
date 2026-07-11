import melee
import logging

class Bot(object):

    def __init__(self, character=None):
        if not character:
            character = melee.Character.MARIO
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

    def menu(self, gamestate):
        """Per-frame hook that runs at menus *before* ``MenuHelper`` reads
        ``self.character``.

        Override this if your bot needs to mutate ``self.character`` during
        the character-select screen (e.g. to avoid colliding with another
        bot's pick). The default implementation is a no-op so bots that do
        not care about menu logic are unaffected.

        ``fight.py`` is responsible for invoking this each frame while the
        game is in a menu state.
        """
        pass

    def fight(self, gamestate):
        pass