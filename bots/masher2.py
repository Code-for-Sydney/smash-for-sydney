import melee
import logging
import random

from .bot import Bot

class Masher2(Bot):

    def __init__(self, character=None):

        character = random.choice([x for x in melee.enums.Character])

        # repick
        if character == melee.enums.Character.UNKNOWN_CHARACTER:
            character = random.choice([x for x in melee.enums.Character])

        super().__init__(character)
        
        self.buttons = [x for x in melee.enums.Button]
        self.buttons.remove(melee.enums.Button.BUTTON_MAIN)
        self.buttons.remove(melee.enums.Button.BUTTON_START)

    def fight(self, gamestate):

        me = gamestate.players[self.port]
        current_stage = gamestate.stage

        for port, player in gamestate.players.items():
            
            # not fighting ourself
            if port != self.port:

                onleft = me.position.x < player.position.x
                altitude_diff = player.position.y - me.position.y
            
                if me.position.x < melee.stages.EDGE_POSITION[current_stage]:
                    self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, int(onleft), 0.5)

                # jump
                if altitude_diff > 0:
                    self.controller.press_button(melee.enums.Button.BUTTON_X)

                # mash!
                if random.random() < 0.5:
                    self.controller.press_button(random.choice(self.buttons))
                else:
                    self.controller.release_all()
