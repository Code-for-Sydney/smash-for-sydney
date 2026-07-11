import melee

from .bot import Bot

import random


class CheesyKirby(Bot):

    next_state = 0
    release = False
    edge_threshold = 15
    recovering = False

    def __init__(self):
        super().__init__(melee.Character.KIRBY)

    def fight(self, gamestate):
        me = gamestate.players[self.port]

        if me.off_stage or self.recovering:
            self.controller.release_all()
            self._recover(me)
        else:
            # self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 1, 0.5)
            if self.release:
                self.controller.release_all()
                self.release = False
            elif self.next_state == 0:
                self._up_special()
                self.release = True
                self.next_state = 1
            elif self.next_state == 1:
                self._set_x_randomly(me, gamestate.stage)
                self.next_state = 2
            elif self.next_state == 2:
                if random.random() < 0.1:
                    self.next_state = 0
                    self.release = True

    def _up_special(self):
        self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 1.0)
        self.controller.press_button(melee.enums.Button.BUTTON_B)
    
    def _set_x_randomly(self, me, stage):
        edge_position = melee.stages.EDGE_POSITION[stage]
        if me.position.x < 0 and me.position.x < self.edge_threshold - edge_position:
            x = 1
        elif me.position.x > 0 and me.position.x > edge_position - self.edge_threshold:
            x = 0
        else:
            if random.random() < 0.5:
                x = 1
            else:
                x = 0
        self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, x, 0.5)

    def _recover(self, me):
        self.recovering = True
        if me.position.x < 0:
            stick_x = 1.0
        elif me.position.x > 0:
            stick_x = 0.0
        else:
            stick_x = 0.5

        self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, stick_x, 1.0)

        if me.jumps_left > 0:
            self.controller.press_button(melee.enums.Button.BUTTON_X)
        else:
            self.controller.release_button(melee.enums.Button.BUTTON_X)
            self.recovering = False
