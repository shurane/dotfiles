" Vim Settings {{{

set nocompatible            " ignore vi-compatibility

set history=10000           " keep n lines of history
set bs=2                    " set backspace to wrap around to previous line
set whichwrap=~,[,]         " Wrap around lines with ~, left-arrow key, and right-arrow key
set number                  " enable line numbering
set numberwidth=5           " set line numbering to take up 5 lines
set cursorline              " highlights current line

" set highlight mode to bold
highlight CursorLine cterm=bold    
" set background of listchars to brown
"highlight SpecialKey ctermbg=brown

set t_Co=256                " sets Vim to use 256 terminal colors
colorscheme wombat256mod    " nice dark theme
set ruler                   " show the cursor position all the time
set nowrap                  " don't wrap long lines
set textwidth=0             " don't wrap lines on inserts
set linebreak               " break on sane delimiters (like space)
set lcs=trail:·,extends:>,tab:>-   " indicates trailing spaces by '·',  wrapped lines by '>', and tabs by '>-'
set scrolloff=3             " scroll up/down by n instead of 1
set showcmd                 " display incomplete command
set cmdheight=1             " set command bar height
set vb t_vb=""              " Turn visual bell off
set mouse=a                 " use the mouse in console vim

set splitright              " vertical splits split to the right (instead of left)
set pastetoggle=,,          " toggle paste-mode by this mapping
set clipboard+=unnamed      " yanks go onto the global clipboard as well -- this might make a mapping unnecessary

" very informative status line
set statusline=%F%m%r%h%w\ [TYPE=%Y\ %{&ff}]\ [%l/%L\ (%p%%)]

set autochdir               " always switch to the current file directory
set modeline                " allow vim options to be embedded in files
set modelines=5             " found either in first n lines or last n lines
set noautowrite             " don't write on make/shell, and other commands
set autoread                " reload changed files
set hidden                  " look this up -- something about efficient writing
set backup                  " simple backup
set backupext=~             " backup for 'file' is 'file~'
set backupdir=~/.vim/backup " stores all backups here
set directory=~/.vim/swap   " stores all swap files here

set incsearch               " turn on incremental search
set ignorecase              " ignore case for searching
set smartcase               " exclude explicit CAPS from ignorecase

set autoindent              " Turn on auto indent
set tabstop=4               " set tab character to n space
set expandtab               " turn tabs into whitespace
set softtabstop=4           " n spaces are treated as tabs
set shiftwidth=4            " indent width for autoindent
"set foldmethod=marker      " for explicit folds
filetype indent on          " indent depends on filetype
filetype plugin on          " enable plugins 
syntax enable               " Syntax highlighting

if has('persistent_undo')
    set undofile            " Enable persistent undo
    set undodir=~/.vim/undo " Store undofiles in a tmp dir
endif

set cpoptions=yraABceFq
set formatoptions+=tcq
" this formatoption isn't working, it seems
set formatoptions-=r        " don't insert comment after <CR>

" }}}

" Syntax Setup {{{

autocmd BufRead,BufNewFile *.txt setfiletype text
autocmd FileType text set wrap
autocmd FileType cpp set makeprg=clang\ -g\ %\ -o\ %<.out

let python_highlight_all=1
set tags+=tags;$HOME

" }}}

" Functions {{{

" Syntax toggle
function! ToggleSyntax()
    if exists("g:syntax_on")
        syntax off
    else
        syntax enable
    endif
endfunction

" Diff Toggle
function! ToggleDiff()
    if &diff
        diffoff
    else
        diffthis
    endif
endfunction

function! Timestamp()
    return "Last Modified: " . strftime("%d %b %Y %X")
endfunction

" Tmux integration
function! TmuxWindowMotion(dir)
    let dict = { 
               \'h' : '-L', 
               \'j' : '-D', 
               \'k' : '-U', 
               \'l' : '-R' 
               \}

    let old_winnr = winnr()
    execute 'wincmd ' . a:dir
    if old_winnr != winnr()
        return
    endif

    call system('tmux select-pane ' . dict[a:dir])
endfunction

function! SetupVAM(features)
    "totally ripped from vim_addon_MarcWeber.vim
    set runtimepath+=~/vim-addons/vim-addon-manager
    let plugins = {
                \ 'always' : ['nerdcommenter']
                \}
    let activate = []
    for [k,v] in items(plugins)
        if k == 'always'
                \ || (type(a:features) == type([]) && index(a:features, k) >=0)
                \ || (type(a:features) == type('') && a:features == 'all')
            call extend(activate,v)
        endif
    endfor

    call vam#ActivateAddons(activate, {'auto_install' : 1})
endfunction

" }}}

" Vim Maps {{{

let mapleader = ","

" swap keys TODO what is this?
nnoremap ' `
nnoremap ` '

" save a file as root
cabbrev w!! w !sudo tee % > /dev/null<CR>:e!<CR><CR>

" insert timestamp in place
iabbrev YTS <C-R>=Timestamp()<CR>

" reload .vimrc
nnoremap <Leader>r :source $MYVIMRC<CR>

" zl is less folds, zm is more folds
" z(j/k) navigates between next/prev fold
nnoremap zl zr
nnoremap zL zR
" to not throw me off with scrolling
nnoremap zh ""

" mappings during insert mode
" when using C-u/C-w in insert mode, create a new change instead of appending
inoremap <C-u> <C-g>u<C-u>
inoremap <C-w> <C-g>u<C-w>
" escape while in insert-mode
inoremap jj <Esc>

" insert newline without going into insert-mode
nnoremap <CR> o<Esc>

" copy and paste to global clipboard using leader key
nnoremap <Leader>m "+p
vnoremap <Leader>m "+p
vnoremap <Leader>n "+y

" do :ls before switching buffers
nnoremap <leader>b :ls<CR>:b<space>

" split vertically and horizontally
" C-w s/v already exist for these two cases
nnoremap <Leader>v :vsplit<CR>
nnoremap <Leader>h :split<CR>

" toggle 
nnoremap <Leader>ts :call ToggleSyntax()<CR>        " syntax
nnoremap <Leader>td :call ToggleDiff()<CR>          " diff
nnoremap <Leader>tw :set wrap!<CR>                  " wrap
nnoremap <Leader>tl :set list!<CR>                  " listchars
nnoremap <C-l> :set hlsearch!<CR>                   " highlight
" TODO kind of incomplete?
nnoremap <Leader>c :setlocal invspell spellang=en_us<CR>

" }}}

" Plugin Setup {{{

" }}}

" Plugin Maps {{{

" shortcuts for NERDTree
nnoremap <Leader>tt :NERDTreeToggle<CR>
let NERDTreeMapActivateNode='<CR>'

" shortcuts for tmux integration
nnoremap <silent> <C-w>h :call TmuxWindowMotion('h')<cr>
nnoremap <silent> <C-w>j :call TmuxWindowMotion('j')<cr>
nnoremap <silent> <C-w>k :call TmuxWindowMotion('k')<cr>
nnoremap <silent> <C-w>l :call TmuxWindowMotion('l')<cr>

" }}}

" vim:fdm=marker:fdl=1
