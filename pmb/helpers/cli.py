# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import logging
import os
import re
import readline
import sys

import pmb.config


class ReadlineTabCompleter:
    """ Stores intermediate state for completer function """
    def __init__(self, options):
        """
        :param options: list of possible completions
        """
        self.options = sorted(options)
        self.matches = []

    def completer_func(self, input_text, iteration):
        """
        :param input_text: text that shall be autocompleted
        :param iteration: how many times "tab" was hit
        """
        # First time: build match list
        if iteration == 0:
            if input_text:
                self.matches = [s for s in self.options
                                if s and s.startswith(input_text)]
            else:
                self.matches = self.options[:]

        # Return the N'th item from the match list, if we have that many.
        if iteration < len(self.matches):
            return self.matches[iteration]
        return None


def ask(question="Continue?", choices=["y", "n"], default="n",
        lowercase_answer=True, validation_regex=None, complete=None):
    """
    Ask a question on the terminal.
    :param question: display prompt
    :param choices: short list of possible answers,
                    displayed after prompt if set
    :param default: default value to return if user doesn't input anything
    :param lowercase_answer: if True, convert return value to lower case
    :param validation_regex: if set, keep asking until regex matches
    :param complete: set to a list to enable tab completion
    """
    styles = pmb.config.styles

    while True:
        date = datetime.datetime.now().strftime("%H:%M:%S")
        line = question
        if choices:
            line += f" ({str.join('/', choices)})"
        if default:
            line += f" [{default}]"
        line_color = f"[{date}] {styles['BOLD']}{line}{styles['END']}"
        line = f"[{date}] {line}"

        if complete:
            readline.parse_and_bind('tab: complete')
            delims = readline.get_completer_delims()
            if '-' in delims:
                delims = delims.replace('-', '')
                readline.set_completer_delims(delims)
            readline.set_completer(
                ReadlineTabCompleter(complete).completer_func)

        ret = input(f"{line_color}: ")

        # Stop completing (question is answered)
        if complete:
            # set_completer(None) would use the default file system completer
            readline.set_completer(lambda text, state: None)

        if lowercase_answer:
            ret = ret.lower()
        if ret == "":
            ret = str(default)

        pmb.helpers.logging.logfd.write(f"{line}: {ret}\n")
        pmb.helpers.logging.logfd.flush()

        # Validate with regex
        if not validation_regex:
            return ret

        pattern = re.compile(validation_regex)
        if pattern.match(ret):
            return ret

        logging.fatal("ERROR: Input did not pass validation (regex: " +
                      validation_regex + "). Please try again.")


def confirm(args, question="Continue?", default=False, no_assumptions=False):
    """
    Convenience wrapper around ask for simple yes-no questions with validation.

    :param no_assumptions: ask for confirmation, even if "pmbootstrap -y'
                           is set
    :returns: True for "y", False for "n"
    """
    default_str = "y" if default else "n"
    if args.assume_yes and not no_assumptions:
        logging.info(question + " (y/n) [" + default_str + "]: y")
        return True
    answer = ask(question, ["y", "n"], default_str, True, "(y|n)")
    return answer == "y"


def progress_print(args, progress):
    """
    Print a snapshot of a progress bar to STDOUT. Call progress_flush to end
    printing progress and clear the line. No output is printed in
    non-interactive mode.

    :param progress: completion percentage as a number between 0 and 1
    """
    width = 79
    try:
        width = os.get_terminal_size().columns - 6
    except OSError:
        pass
    chars = int(width * progress)
    filled = "\u2588" * chars
    empty = " " * (width - chars)
    percent = int(progress * 100)
    if pmb.config.is_interactive and not args.details_to_stdout:
        sys.stdout.write(f"\u001b7{percent:>3}% {filled}{empty}")
        sys.stdout.flush()
        sys.stdout.write("\u001b8\u001b[0K")


def progress_flush(args):
    """
    Finish printing a progress bar. This will erase the line. Does nothing in
    non-interactive mode.
    """
    if pmb.config.is_interactive and not args.details_to_stdout:
        sys.stdout.flush()
