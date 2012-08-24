[ -z "$PS1" ] && return             # If not running interactively, don't do anything

HISTCONTROL=ignoredups:ignorespace  # force ignoredups and ignorespace
HISTSIZE=200000
HISTFILESIZE=200000
shopt -s histappend                 # append to the history file, don't overwrite it
# Save and reload the history after each command finishes
# taken from http://stackoverflow.com/a/3055135/198348
export PROMPT_COMMAND="history -a; history -c; history -r; $PROMPT_COMMAND"
#export PROMPT_COMMAND="history -a; $PROMPT_COMMAND"
shopt -s checkwinsize               # update the values of LINES and COLUMNS after each command

# break on '-' and '/' for 'C-w' properly! look at .inputrc for backward-kill-word
# TODO and look at other stty options
stty werase undef
# disable terminal flow control
stty -ixon

export INPUTRC="$HOME/.inputrc"
export PAGER="less"
export LESS="-R"
export USE_CCACHE=1
export CCACHE_DIR="$HOME/.ccache"

export XDG_DATA_HOME="$HOME/.local/share"
export EDITOR="vim"
#export ECLIPSE_HOME="~/cs/eclipse"
export WORKON_HOME="$HOME/projects/python_envs"

export CABAL_PATH=".cabal/bin"
export RUBY_PATH="/var/lib/gems/1.8/bin"

export PATH=$HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games
export PATH="$CABAL_PATH:$RUBY_PATH:$PATH"

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
# TODO why have this and the color prompt above?
case "$TERM" in
    xterm*|rxvt*)
        PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"
        ;;
    *)
        ;;
esac

# Setting up extra commands if they exist.
# ====
command -v "bash_completion_tmux.sh" >/dev/null && source "bash_completion_tmux.sh"
command -v "virtualenvwrapper.sh" >/dev/null && source "/usr/local/bin/virtualenvwrapper.sh"
command -v "pip" >/dev/null && eval "$(pip completion --bash)"

#if [ -f /etc/bash_completion ] && ! shopt -oq posix; then
[[ -s "/etc/bash_completion" ]] && source "/etc/bash_completion"
[[ -s "$HOME/.pythonbrew/etc/bashrc" ]] && source "$HOME/.pythonbrew/etc/bashrc"
[[ -s "$HOME/.bash_aliases" ]] && source "$HOME/.bash_aliases"
[[ -s "$HOME/.rvm/scripts/rvm" ]] && source "$HOME/.rvm/scripts/rvm" # Load RVM into a shell session *as a function*
[[ -s "/etc/profile.d/autojump.bash" ]] && source "/etc/profile.d/autojump.bash"
[[ -s "$HOME/bin/git-completion.bash" ]] && source "$HOME/bin/git-completion.bash"

# For Mac OS X
if command -v "brew" >/dev/null; then
    #for clojure TODO make this version-independent
    export CLASSPATH="/usr/local/Cellar/clojure-contrib/1.2.0/clojure-contrib.jar"
    [[ -s "$(brew --prefix)/etc/autojump.bash" ]] && source "$(brew --prefix)/etc/autojump.bash"
    [[ -s "$(brew --prefix)/etc/bash_completion" ]] && source "$(brew --prefix)/etc/bash_completion"
fi

# Ubuntu specific variable stuff
# TODO this is bad because it's locked to java-6, what if I want something else?
JAVA_6="/usr/lib/jvm/java-6-sun"
if [[ $(lsb_release --id --short) = "Ubuntu" ]] && [[ -s "$JAVA_6/bin/java" ]]; then
    export JAVA_HOME="$JAVA_6"
    export ANDROID_JAVA_HOME="$JAVA_6"
fi
