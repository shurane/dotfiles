# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

HISTCONTROL=ignoredups:ignorespace:erasedups
HISTSIZE=200000
HISTFILESIZE=200000
# append to the history file, don't overwrite it
shopt -s histappend
# save and reload the history after each command finishes
# taken from http://stackoverflow.com/a/3055135/198348
export PROMPT_COMMAND="history -a; history -c; history -r; $PROMPT_COMMAND"
# update the values of lines and columns after each command
shopt -s checkwinsize

# using `tty -s` because of https://askubuntu.com/a/918479/22073
# break on '-' and '/' for 'c-w' properly! look at .inputrc for backward-kill-word
# TODO look at other stty options
tty -s && stty werase undef
# disable terminal flow control
tty -s && stty -ixon

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

export INPUTRC="$HOME/.inputrc"
export PAGER="less"
export EDITOR="vim"
export LESS="-FRXi --incsearch"
export PATH="$HOME/.local/bin:$PATH"

[ -f "$HOME/.ghcup/env" ] && source "$HOME/.ghcup/env" # https://gitlab.haskell.org/haskell/ghcup-hs
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env" # https://rustup.rs/
[ -f "$HOME/.fzf.bash" ] && source "$HOME/.fzf.bash" # https://github.com/junegunn/fzf#key-bindings-for-command-line

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."
alias tree="tree -C"

PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
#PS1='\u@\h:\w\$ '

# https://the.exa.website/
alias ls="ls --human-readable --group-directories-first --sort=extension --color=auto"
test -x "$(command -v exa)" && alias ls="exa --group-directories-first --sort=extension"

test -x "$(command -v cat)" && alias cat=bat
test -x "$(command -v rg)" && alias grep="rg --ignore-case"
test -x "$(command -v vivid)" && export LS_COLORS="$(vivid generate snazzy)"
test -x "$(command -v zoxide)" && eval "$(zoxide init bash)"
test -x "$(command -v nvim)" && alias vim=nvim

# https://github.com/BurntSushi/ripgrep/issues/86#issuecomment-331718946
rgl() { rg -i -p -M 500 "$@" | less -XFR; }
rgf() { rg --files | rg -i -p -M 500 "$@" | less -XFR; }
rglc() { rg -i -p -M 500 --type csharp "$@" | less -XFR; }
rglt() { rg -i -p -M 500 --type ts "$@" | less -XFR; }
rgltj() { rg -i -p -M 500 --type ts --type js "$@" | less -XFR; }
rglweb() { rg -i -p -M 500 --type-add 'web:*.{htm,html,css,sass,less,js,jsx,ts,tsx}' --type web "$@" | less -XFR; }

batdiff() { git diff --name-only --diff-filter=d | xargs bat --diff; }

# https://github.com/junegunn/fzf#respecting-gitignore
#export FZF_DEFAULT_COMMAND='rg --files --hidden -g "!.git"'
export FZF_DEFAULT_COMMAND='fd --hidden --exclude .git'

