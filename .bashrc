# ~/.bashrc: executed by bash(1) for non-login shells.

[ -z "$PS1" ] && return             # If not running interactively, don't do anything
HISTCONTROL=ignoredups:ignorespace  # force ignoredups and ignorespace
shopt -s histappend                 # append to the history file, don't overwrite it
HISTSIZE=20000
HISTFILESIZE=20000
shopt -s checkwinsize               # update the values of LINES and COLUMNS after each command

export XDG_DATA_HOME="$HOME/.local/share"
export EDITOR="vim"
export ECLIPSE_HOME="~/cs/eclipse"
#export JAVA_HOME=/usr/lib/jvm/java-6-openjdk/
export INPUTRC="$HOME/.inputrc"
export PAGER="less"
export LESS="-R"

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "$debian_chroot" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

force_color_prompt=yes
if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	    color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt force_color_prompt

# If this is an xterm set the title to user@host:dir
# may do wonky things on other terminals, perhaps?
PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"

if [ -f /usr/local/bin/virtualenvwrapper.sh ]; then
    . /usr/local/bin/virtualenvwrapper.sh
fi

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

if [ -f /etc/bash_completion ] && ! shopt -oq posix; then
    . /etc/bash_completion
fi

if command -v "bash_completion_tmux.sh" >/dev/null; then
    . "bash_completion_tmux.sh"
fi
