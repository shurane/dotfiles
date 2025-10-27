
setopt histignorealldups
setopt inc_append_history
setopt share_history

autoload -U colors && colors
autoload -U select-word-style && select-word-style bash
autoload -Uz compinit && compinit

# https://superuser.com/questions/458906/zsh-tab-completion-of-git-commands-is-very-slow-how-can-i-turn-it-off, zsh completion kinda slow
fpath=(~/.zsh $fpath)

# matches the style of bashrc with `username@host:dir$`
# see https://zsh-prompt-generator.site/ and https://stackoverflow.com/questions/689765/how-can-i-change-the-color-of-my-prompt-in-zsh-different-from-normal-text
export PROMPT="%{$fg[green]%}%n@%m%{$reset_color%}:%{$fg[blue]%}%~%{$reset_color%}$ "
export EDITOR=nvim
export LESS="-FRXi --incsearch"
export HISTSIZE=200000
export SAVEHIST=200000

eval "$(/opt/homebrew/bin/brew shellenv)"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."
alias .......="cd ../../../../../.."

# alias rm="grm"
test -x "$(command -v eza)" && alias ls="eza --group-directories-first --sort=extension"
test -x "$(command -v eza)" && alias lt="eza --group-directories-first --sort=extension --long --tree"
test -x "$(command -v bat)" && alias cat=bat
test -x "$(command -v rg)" && alias grep="rg --ignore-case"
test -x "$(command -v vivid)" && export LS_COLORS="$(vivid generate snazzy)"
#test -x "$(command -v fasd)" && eval "$(fasd --init auto)"
test -x "$(command -v zoxide)" && eval "$(zoxide init zsh)"
test -x "$(command -v nvim)" && alias vim=nvim
test -x "$(command -v nvim)" && alias view="nvim -R"
test -f $HOME/.fzf.zsh && source $HOME/.fzf.zsh

# https://github.com/BurntSushi/ripgrep/issues/86#issuecomment-331718946
rgf() { rg --files | rg -i -p -M 500 "$@" | less -XFRi; }
rgl() { rg -i -p -M 500 "$@" | less -XFRi; }
rglp() { rg -i -p -M 500 --type protobuf "$@" | less -XFRi; }
rglj() { rg -i -p -M 500 --type java "$@" | less -XFRi; }
rglt() { rg -i -p -M 500 --type ts "$@" | less -XFRi; }
rgltj() { rg -i -p -M 500 --type ts --type js "$@" | less -XFRi; }
rglweb() { rg -i -p -M 500 --type-add 'web:*.{htm,html,css,sass,less,js,jsx,ts,tsx}' --type web "$@" | less -XFRi; }

# vim-mode emulation, with some emacs-style readline to boot
# check zshzle for more options
bindkey -v

bindkey -M viins 'jj' vi-cmd-mode
bindkey -M viins '^K' kill-line
bindkey -M viins '^U' backward-kill-line
bindkey -M viins '^W' backward-kill-word
bindkey -M viins '^?' backward-delete-char
bindkey -M viins '^h' backward-delete-char
bindkey -M viins '^R' history-incremental-search-backward
bindkey -M viins '^S' history-incremental-search-forward
bindkey -M viins '^P' up-line-or-history
bindkey -M viins '^N' down-line-or-history
bindkey -M viins '^A' beginning-of-line
bindkey -M viins '^E' end-of-line
bindkey -M viins 'b' vi-backward-word
bindkey -M viins 'f' vi-forward-word

# https://dougblack.io/words/zsh-vi-mode.html
function zle-line-init zle-keymap-select {
    VIM_PROMPT="%{$fg_bold[yellow]%} [% NORMAL]% %{$reset_color%}"
    RPS1="${${KEYMAP/vicmd/$VIM_PROMPT}/(main|viins)/} $EPS1"
    zle reset-prompt
}
zle -N zle-line-init
zle -N zle-keymap-select
#export KEYTIMEOUT=1

