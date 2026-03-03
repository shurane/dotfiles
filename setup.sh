# third party binaries, installed manually
: << END
- neovim https://github.com/neovim/neovim/wiki/Installing-Neovim#appimage-universal-linux-package
- ripgrep https://github.com/BurntSushi/ripgrep#installation
- tokei https://github.com/XAMPPRocky/tokei (cloc, but faster. there's also scc)
- sharkdp/fd https://github.com/sharkdp/fd (find alternative)
- sharkdp/bat https://github.com/sharkdp/bat (cat alternative with syntax highlighting)
- sharkdp/vivid https://github.com/sharkdp/vivid (LS_COLORS for different file extensions)
- sharkdp/diskus https://github.com/sharkdp/diskus (du -sh alternative that's parallelized)
- dundee/gdu alternative to du and ncdu https://github.com/dundee/gdu
- dandavision/delta https://github.com/dandavison/delta
- zoxide (successor to fasd, autojump) https://github.com/ajeetdsouza/zoxide
- broot https://github.com/Canop/broot (CLI file manager)
- ranger https://github.com/ranger/ranger (CLI file manager, with vim bindings)
- bkt https://github.com/dimo414/bkt (for caching command output)
- glow CLI markdown renderer, https://github.com/charmbracelet/glow
- nb note taking tool, https://github.com/xwmx/nb
- fastfetch - show system info, kind of like motd or neofetch https://github.com/fastfetch-cli/fastfetch
- plt/racket
- rustup
- ghcup
- ziglang
END

sudo pacman -S 7zip ripgrep neovim nodejs clang gcc tmux rsync btop zoxide gdu glow fd bat vivid tokei git-delta lazygit broot ranger fastfetch
# use `npx --yes` with http-server@latest, serve@latest, nodemon, tsc@latest, tsx@latest, oxlint@latest, biome@latest

# share neovim configuration between default user and root:
sudo mkdir -p /root/.config && sudo ln -s $HOME/dotfiles/nvim /root/.config/nvim
