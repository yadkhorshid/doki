import sys


def run():
    if "--cli" in sys.argv[1:]:
        from .cli import console_main

        console_main()
    else:
        from .gui import main

        main()


if __name__ == "__main__":
    run()
