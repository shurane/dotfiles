[ -z "$PS1" ] && return             # If not running interactively, don't do anything
# TODO this .bashrc is still slow. Cut the cruft.

HISTCONTROL=ignoredups:ignorespace  # force ignoredups and ignorespace
HISTSIZE=200000
HISTFILESIZE=200000
shopt -s histappend                 # append to the history file, don't overwrite it
# Save and reload the history after each command finishes
# taken from http://stackoverflow.com/a/3055135/198348
export PROMPT_COMMAND="history -a; history -c; history -r; $PROMPT_COMMAND"
shopt -s checkwinsize               # update the values of LINES and COLUMNS after each command

# break on '-' and '/' for 'C-w' properly! look at .inputrc for backward-kill-word
# TODO and look at other stty options
stty werase undef
# disable terminal flow control
stty -ixon

export INPUTRC="$HOME/.inputrc"
export PAGER="less"
export EDITOR="vim"
export LESS="-R"

source $HOME/.pathrc


# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '

# If this is an xterm set the title to user@host:dir
# may do wonky things on other terminals, perhaps?
# TODO why have this and the color prompt above?
case "$TERM" in
    xterm*|rxvt*)
        PS1="\[\e]0;\u@\h: \w\a\]$PS1"
        ;;
    *)
        ;;
esac

source $HOME/.loadrc
