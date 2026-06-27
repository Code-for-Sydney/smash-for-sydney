import signal
import melee
import logging

slippi_path = "C:/Users/sibun/AppData/Roaming/Slippi Launcher/netplay/"
iso = "C:/Users/sibun/Documents/Games/Gamecube/Super Smash Bros. Melee (USA) (En,Ja) (Rev 2).nkit.iso"

def fight(stage, players):

    console = melee.Console(path=slippi_path, fullscreen=True)

    port = 1
    for player in players:
        player.create_controller(console, port)
        port += 1

    console.run(iso_path=iso)

    logging.info("Connecting to console...")
    if not console.connect():
        logging.error("ERROR: Failed to connect to the console.")
        sys.exit(-1)
    logging.info("Console connected")

    for player in players:
        player.connect()

    menu_helper = melee.MenuHelper()

    while True:

        gamestate = console.step()
   
        if gamestate.menu_state in [melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH]:
            for player in players:
                player.fight(gamestate)
        else:
            for player in players:
                menu_helper.menu_helper_simple(
                gamestate,
                player.controller,
                player.character,
                stage,
                "",
                autostart=True,
                swag=False)
