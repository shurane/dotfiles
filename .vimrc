set nocompatible            " ignore vi-compatibility

set history=1000            " keep n lines of history
set bs=2                    " set backspace to wrap around to previous line
set whichwrap=~,[,]         " Wrap around lines with ~, left-arrow key, and right-arrow key
set number                  " enable line numbering
set numberwidth=5           " set line numbering to take up 5 lines
set cursorline              " highlights current line
hi CursorLine cterm=bold    " sets highlight mode to bold
set t_Co=256                " sets Vim to use 256 terminal colors
set ruler                   " show the cursor position all the time
set nowrap                  " don't wrap long lines
set linebreak               " break on sane delimiters (like space)
set lcs=trail:·,extends:>,tab:>-   " indicates trailing spaces by '·',  wrapped lines by '>', and tabs by '>-'
set scrolloff=3             " scroll up/down by 3 instead of 1
set showcmd                 " display incomplete command
set cmdheight=1             " set command bar height
set vb t_vb=""              " Turn visual bell off
set mouse=a                 " use the mouse in console vim

" very informative status line
set statusline=%F%m%r%h%w\ [TYPE=%Y\ %{&ff}]\ [%l/%L\ (%p%%)]

set autochdir               " always switch to the current file directory
set hidden                  " look this up -- something about efficient writing
set backup                  " simple backup
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
filetype indent on          " indent depends on filetype
filetype plugin on          " enable plugins 
syntax on                   " Syntax highlighting

set cpoptions=yraABceFsmq
"             |||||||||||
"             ||||||||||+-- When joining lines, leave the cursor
"             |||||||||      between joined line
"             |||||||||+-- When a new match is created (showmatch)
"             ||||||||      pause for .5
"             ||||||||+-- Set buffer options when entering the
"             |||||||      buffer
"             |||||||+-- :write command updates current file name
"             ||||||+-- Automatically add <CR> to the last line
"             |||||      when using :@r
"             |||||+-- Searching continues at the end of the match
"             ||||      at the cursor position
"             ||||+-- A backslash has no special meaning in mapping
"             |||+-- :write updates alternative file name
"             ||+-- :read updates alternative file name
"             |+-- '.' can redo search ('/') commands
"             +-- '.' can redo yank commands

autocmd BufRead,BufNewFile *.txt setfiletype text
autocmd FileType text set wrap
autocmd FileType cpp set makeprg=g++\ -g\ %\ -o\ %<.out
autocmd FileType c,cpp source ~/.vim/ftplugin/cpp/opengl.vim
let python_highlight_all=1
let g:pydiction_location = '~/.vim/plugin/pydiction/complete-dict'
set tags+=tags;$HOME

" Mapping time!
let mapleader = ","

" swap keys
nnoremap ' `
nnoremap ` '

"shortcuts for NERDTree
nnoremap <Leader>d :NERDTreeToggle<CR>
let NERDTreeMapActivateNode='<CR>'

" reload .vimrc
nnoremap <Leader>r :source $MYVIMRC<CR>

" toggle listchars (tabs, spaces, etc)
nnoremap <Leader>v :set list!<CR>

" toggle spelling on and off - kind of incomplete
nnoremap <Leader>c :setlocal invspell spellang=en_us<CR>

" remove highlighting
nnoremap <C-l> :set hlsearch!<CR><C-l>
" When using C-u/C-w in insert mode, create a new change instead of appending
inoremap <C-u> <C-g>u<C-u>
inoremap <C-w> <C-g>u<C-w>
" insert newline without going into insert-mode
nnoremap <CR> o<Esc>
" escape while in insert-mode
inoremap jj <Esc>
" copy and paste using leader key
nnoremap <Leader>m "+p
nnoremap <Leader>n "+y
vnoremap <Leader>n "+y
" do :ls before switching buffers -- might forget when I merge this with other
" vimrc
 map <leader>l :ls<CR>:b<space>

" split vertically
"nnoremap <Leader>v :vsp<Enter>
" toggle syntax on and off -- also an ugly function
nnoremap <Leader>s :if exists("syntax_on") <Bar>
    \   syntax off <Bar>
    \ else <Bar>
    \   syntax enable <Bar>
    \ endif <Enter>

set pastetoggle=,,
