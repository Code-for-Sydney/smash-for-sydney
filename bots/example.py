import melee
import logging

from .bot import Bot

class Example(Bot):

    def __init__(self, character=None):
        super().__init__(character)

    def fight(self, gamestate):

        me = gamestate.players[self.port]

        if gamestate.distance <= 4:
            self.controller.press_button(melee.enums.Button.BUTTON_B)
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0)
        else:
            
            for port, player in gamestate.players.items():
                if port != self.port:
                    onleft = me.position.x < player.position.x
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, int(onleft), 0.5)