[ -z "$PS1" ] && return             # If not running interactively, don't do anything
# TODO this .bashrc is still slow. Cut the cruft.

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
export EDITOR="vim"
export LESS="-R"
export USE_CCACHE=1
export CCACHE_DIR="$HOME/.ccache"
#export ECLIPSE_HOME="~/cs/eclipse"
export XDG_DATA_HOME="$HOME/.local/share"
export WORKON_HOME="$HOME/projects/python_envs"
export CLOJURESCRIPT_HOME="$HOME/projects-vanilla/clojurescript/script"
export VENDOR_PERL="/usr/bin/vendor_perl"

PATHS_TO_ADD=( 
               "$HOME/bin"
               "$VENDOR_PERL"
               "/usr/local/sbin"
               "/usr/local/bin"
               "/usr/sbin"
               "/usr/bin"
               "/bin"
             )

[[ -n "$JAVA_HOME" ]] && PATHS_TO_ADD+=("$JAVA_HOME/bin")

# http://stackoverflow.com/a/5905019/198348
export PATH=$(set -- ${PATHS_TO_ADD[@]}; IFS=:; echo "$*")

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

## for ARCH_LINUX
#[[ $(lsb_release --id --short) = "archlinux" ]] && export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python2

# TODO this should be cleaned up somehow..., so many extra commands
command -v "virtualenvwrapper.sh" >/dev/null && source $(which virtualenvwrapper.sh)
command -v "pip" >/dev/null && eval "$(pip completion --bash)"

# fasd setup and aliases
eval "$(fasd --init auto)"
#alias v='f -t -e vim -b viminfo'
#alias m='f -e mplayer' # quick opening files with mplayer
#alias o='a -e xdg-open' # quick opening files with xdg-open

[[ -s "$HOME/.bash_aliases" ]] && source "$HOME/.bash_aliases"

## bash completions are sloooow.
#[[ -s "/usr/share/bash-completion/bash_completion" ]] && source "/usr/share/bash-completion/bash_completion"
#[[ -s "/etc/bash_completion" ]] && source "/etc/bash_completion"
#[[ -s "$HOME/bin/git-completion.bash" ]] && source "$HOME/bin/git-completion.bash"
[[ -s $HOME/.rvm/scripts/rvm ]] && source "$HOME/.rvm/scripts/rvm" # Load RVM into a shell session *as a function*
[[ -s $HOME/.nvm/nvm.sh ]] && . $HOME/.nvm/nvm.sh # This loads NVM
[[ -s $HOME/.tmuxinator/scripts/tmuxinator ]] && source $HOME/.tmuxinator/scripts/tmuxinator
#PATH=$PATH:$HOME/.rvm/bin # Add RVM to PATH for scripting

# Mac OS X
if command -v "brew" >/dev/null; then
    true
fi

# Ubuntu 
if [[ $(lsb_release --id --short) = "Ubuntu" ]] && [[ -s "$JAVA_6/bin/java" ]]; then
    JAVA_6="/usr/lib/jvm/java-6-sun"
    export JAVA_HOME="$JAVA_6"
    export ANDROID_JAVA_HOME="$JAVA_6"
fi

