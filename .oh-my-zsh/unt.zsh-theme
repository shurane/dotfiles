function box_name {
    echo "$USER@$HOST"
}

# this stuff is way more confusing than it needs be
PROMPT='%{$fg_bold[red]%}➜ %{$fg_bold[blue]%}$(git_prompt_info)%{$fg_bold[blue]%}% %{$reset_color%}'
RPROMPT='%{$fg[cyan]%}%4c %{$fg_bold[green]%}% $(box_name)% %{$reset_color%}'


ZSH_THEME_GIT_PROMPT_PREFIX="git:(%{$fg[red]%}"
ZSH_THEME_GIT_PROMPT_SUFFIX="%{$reset_color%}"
ZSH_THEME_GIT_PROMPT_DIRTY="%{$fg[blue]%}) %{$fg[yellow]%}✗%{$reset_color%}"
ZSH_THEME_GIT_PROMPT_CLEAN="%{$fg[blue]%})"
