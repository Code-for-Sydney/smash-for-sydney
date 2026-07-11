import melee
from melee import stages

from .bot import Bot


class LinyuPikachu(Bot):
    """A readable first bot: move toward the opponent, poke, attack, and recover."""

    def __init__(self, character=None):
        super().__init__(melee.Character.PIKACHU)
        self.frame = 0

    def fight(self, gamestate):
        self.frame += 1

        me = gamestate.players.get(self.port)
        opponent = self._get_opponent(gamestate)
        if not me or not opponent:
            self.controller.release_all()
            return

        if me.hitstun_frames_left > 0:
            self._survive(gamestate, me)
            return

        if self._needs_recovery(gamestate, me):
            self._recover(gamestate, me)
            return

        if not me.on_ground:
            self._air_attack(me, opponent)
            return

        distance = abs(opponent.position.x - me.position.x)
        vertical_gap = opponent.position.y - me.position.y

        if distance > 45:
            self._move_toward(me, opponent)
        elif distance > 18:
            self._thunder_jolt(me, opponent)
        elif vertical_gap > 14:
            self._attack_up()
        elif self._should_shield(opponent):
            self._shield()
        else:
            self._close_attack(me, opponent)

    def _get_opponent(self, gamestate):
        opponents = [
            player
            for port, player in gamestate.players.items()
            if port != self.port and player.stock > 0
        ]
        if not opponents:
            return None

        me = gamestate.players.get(self.port)
        if not me:
            return None
        return min(
            opponents,
            key=lambda player: abs(player.position.x - me.position.x),
        )

    def _needs_recovery(self, gamestate, me):
        edge = stages.EDGE_GROUND_POSITION.get(gamestate.stage, 70)
        return me.off_stage or abs(me.position.x) > edge - 8 or me.position.y < -8

    def _recover(self, gamestate, me):
        edge = stages.EDGE_GROUND_POSITION.get(gamestate.stage, 70)
        center_x = 0.5
        toward_stage = 0.65 if me.position.x < 0 else 0.35

        if abs(me.position.x) > edge + 8:
            x = toward_stage
        else:
            x = center_x

        if me.jumps_left > 0 and self.frame % 18 == 0:
            self.controller.simple_press(x, 1.0, melee.Button.BUTTON_Y)
        elif self.frame % 8 in (0, 1, 2):
            self.controller.simple_press(x, 1.0, melee.Button.BUTTON_B)
        else:
            self.controller.simple_press(x, 0.8, None)

    def _survive(self, gamestate, me):
        edge = stages.EDGE_GROUND_POSITION.get(gamestate.stage, 70)
        x = 0.7 if me.position.x < -edge / 2 else 0.3
        self.controller.simple_press(x, 0.75, None)

    def _move_toward(self, me, opponent):
        x = 1.0 if opponent.position.x > me.position.x else 0.0
        self.controller.simple_press(x, 0.5, None)

    def _thunder_jolt(self, me, opponent):
        x = 1.0 if opponent.position.x > me.position.x else 0.0
        if self.frame % 24 < 4:
            self.controller.simple_press(x, 0.5, melee.Button.BUTTON_B)
        else:
            self.controller.simple_press(x, 0.5, None)

    def _air_attack(self, me, opponent):
        x = 1.0 if opponent.position.x > me.position.x else 0.0
        if abs(opponent.position.x - me.position.x) < 20:
            self.controller.simple_press(x, 0.5, melee.Button.BUTTON_A)
        else:
            self.controller.simple_press(x, 0.5, None)

    def _attack_up(self):
        self.controller.simple_press(0.5, 1.0, melee.Button.BUTTON_A)

    def _should_shield(self, opponent):
        attacking_actions = {
            melee.Action.DASH_ATTACK,
            melee.Action.NEUTRAL_ATTACK_1,
            melee.Action.NEUTRAL_ATTACK_2,
            melee.Action.NEUTRAL_ATTACK_3,
            melee.Action.FTILT_MID,
            melee.Action.UPTILT,
            melee.Action.DOWNTILT,
            melee.Action.FSMASH_MID,
            melee.Action.UPSMASH,
            melee.Action.DOWNSMASH,
            melee.Action.NAIR,
            melee.Action.FAIR,
            melee.Action.BAIR,
            melee.Action.UAIR,
            melee.Action.DAIR,
        }
        return opponent.action in attacking_actions and opponent.action_frame < 12

    def _shield(self):
        self.controller.simple_press(0.5, 0.5, melee.Button.BUTTON_L)

    def _close_attack(self, me, opponent):
        toward_opponent = 1.0 if opponent.position.x > me.position.x else 0.0

        if opponent.percent > 75 and self.frame % 18 < 5:
            self.controller.simple_press(toward_opponent, 1.0, melee.Button.BUTTON_A)
        elif self.frame % 30 < 6:
            self.controller.simple_press(toward_opponent, 0.5, melee.Button.BUTTON_Z)
        else:
            self.controller.simple_press(toward_opponent, 0.5, melee.Button.BUTTON_A)
