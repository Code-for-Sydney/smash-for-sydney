import os
import sys
import signal
import melee
import logging

slippi_path = os.getenv("SLIPPI_PATH", None)
iso = os.getenv("SMASH_ISO_PATH", None)

def fight(stage, players):

    if not slippi_path:
        logging.error("SLIPPI_PATH env var not defined")
        raise RuntimeError

    if not iso:
        logging.error("SMASH_ISO_PATH env var not defined")
        raise RuntimeError

    console = melee.Console(path=slippi_path, fullscreen=False)

    port = 1
    for player in players:
        player.create_controller(console, port)
        port += 1

    def signal_handler(sig, frame):
        for player in players:
            player.controller.disconnect()
        console.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    console.run(iso_path=iso)

    logging.info("Connecting to console...")
    if not console.connect():
        logging.error("ERROR: Failed to connect to the console.")
        sys.exit(-1)
    logging.info("Console connected")

    for player in players:
        player.connect()

    menu_helper = melee.MenuHelper()

    game_rounds = 3
    in_menu = False
    while True:

        gamestate = console.step()
   
        if gamestate.menu_state in [melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH]:
            in_menu = False
            for player in players:
                player.fight(gamestate)
        else:
            for player in players:
                # Give each bot one chance per menu frame to update
                # ``self.character`` before ``menu_helper_simple`` consumes
                # it. The base ``Bot.menu`` is a no-op, so bots that do not
                # override it are unaffected.
                player.menu(gamestate)
                menu_helper.menu_helper_simple(
                gamestate,
                player.controller,
                player.character,
                stage,
                "",
                autostart=True,
                swag=False)
            if not in_menu:
                in_menu = True
                print("ROUND", game_rounds)
                game_rounds -= 1
                if game_rounds < 0:
                    exit()
