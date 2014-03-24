set nocompatible               " be iMproved

filetype off                   " required!

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()

" let Vundle manage Vundle
" required!
Bundle 'gmarik/vundle'

" My Bundles here:
"
" original repos on github
Bundle 'scrooloose/nerdcommenter'
Bundle 'scrooloose/nerdtree'
Bundle 'scrooloose/syntastic'
Bundle 'tpope/vim-repeat'
Bundle 'tpope/vim-fugitive'
Bundle 'tpope/vim-markdown'
Bundle 'tpope/vim-surround'
Bundle 'tpope/vim-unimpaired'
Bundle 'tpope/vim-rsi'
Bundle 'mileszs/ack.vim'
Bundle 'michalbachowski/vim-wombat256mod'
Bundle 'kien/ctrlp.vim'
Bundle 'vim-scripts/matchit.zip'
Bundle 'sjl/gundo.vim'
Bundle 'nathanaelkane/vim-indent-guides'
Bundle 'airblade/vim-gitgutter'
Bundle 'Shougo/neocomplete'
Bundle 'majutsushi/tagbar'
Bundle 'gregsexton/gitv'

" vim-scripts repos
" non github repos

filetype plugin indent on     " required!
syntax enable

" Vim Settings {{{

set t_Co=256
colorscheme wombat256mod
set history=10000           " keep n lines of history
set bs=2                    " set backspace to wrap around to previous line
set whichwrap=~,[,]         " Wrap around lines with ~, left-arrow key, and right-arrow key
set number                  " enable line numbering
set numberwidth=5           " set line numbering to take up 5 lines
set cursorline              " highlights current line

"set t_Co=256                " colors!
set ruler                   " show the cursor position all the time
set nowrap                  " don't wrap long lines
set showbreak=>\ \ \        " for wrapped lines
set textwidth=0             " don't wrap lines on inserts
set linebreak               " break on sane delimiters (like space)
set lcs=trail:-,extends:>,tab:>-,eol:$   " indicates trailing spaces by '-',  wrapped lines by '>', and tabs by '>-'
set scrolloff=3             " scroll up/down by n instead of 1
set showcmd                 " display incomplete command
set cmdheight=1             " set command bar height
set vb t_vb=""              " Turn visual bell off
set mouse=a                 " use the mouse in console vim
set mousehide

set splitright              " vertical splits split to the right (instead of left)
set clipboard+=unnamed      " yanks go onto the global clipboard as well -- this might make a mapping unnecessary

" very informative status line, but should document later
set statusline=%F%m%r%h%w\ [TYPE=%Y\ %{&ff}]\ [%l/%L\ (%p%%)]%=%{fugitive#statusline()}
set laststatus=2            " always keep status line on

set autochdir               " always switch to the current file directory
set modeline                " allow vim options to be embedded in files
set modelines=5             " found either in first n lines or last n lines
set noautowrite             " don't write on make/shell, and other commands
set autoread                " reload changed files
set hidden                  " look this up -- something about efficient writing
set backup                  " simple backup
set backupext=~             " backup for 'file' is 'file~'

let required_dirs = ['$HOME/.vim','$HOME/.vim/backup','$HOME/.vim/swap','$HOME/.vim/undo']
for dir in required_dirs
    if finddir(expand(dir)) == ''
        call mkdir(expand(dir))
    endif
endfor

set backupdir=~/.vim/backup " stores all backups here
set directory=~/.vim/swap   " stores all swap files here

"set nowrapscan              " turn off search wrap
set incsearch               " turn on incremental search
set ignorecase              " ignore case for searching
set smartcase               " exclude explicit CAPS from ignorecase

set autoindent              " Turn on auto indent
set tabstop=4               " set tab character to n space
set expandtab               " turn tabs into whitespace
set softtabstop=4           " n spaces are treated as tabs
set shiftwidth=4            " indent width for autoindent
"set foldmethod=marker      " for explicit folds

set cpoptions=yraABceFq
set formatoptions+=tcq
" this formatoption isn't working, it seems
set formatoptions-=r        " don't insert comment after <CR>

au BufWritePost,BufNewFile,BufRead *.md,*.markdown,*.mdown,*.mkd,*.mkdn set filetype=markdown

" }}}

" Functions {{{

" trim whitespace, from http://vim.wikia.com/wiki/Remove_unwanted_spaces
function! StripTrailingWhitespace()
    normal mZ
    %s/\s\+$//e
    if line("'Z") != line(".")
        echo "Stripped whitespace"
    endif
    normal `Z
endfunction

" toggle syntax
function! ToggleSyntax()
    if exists("g:syntax_on")
        syntax off
    else
        syntax enable
    endif
endfunction

" toggle diff
function! ToggleDiff()
    if &diff
        diffoff
    else
        diffthis
    endif
endfunction

" }}}

" Vim Maps {{{

let mapleader = ","

" save a file as root
" quit without confirmation
" wipe buffer
" open new tab
" open up vimrc in current window
" reload .vimrc
cabbrev w!! w !sudo tee % > /dev/null<CR>:e!<CR><CR>
nnoremap \q :q<CR>
nnoremap \bw :bw<CR>
nnoremap \t :tabedit<CR>
nnoremap \r :e $MYVIMRC<CR>
nnoremap <Leader>r :source $MYVIMRC<CR>

nnoremap <C-w>j <C-w>w
nnoremap <C-w>k <C-w>W
nnoremap <C-w><C-j> <C-w>w
nnoremap <C-w><C-k> <C-w>W

" switch back and forth between buffers
nnoremap `n :bn<CR>
nnoremap `p :bp<CR>
" switch back and forth between tabs
noremap <S-H> gT
noremap <S-L> gt
noremap j gj
noremap k gk

" z(l/r) is less/reduce folds, zm is more folds
" z(j/k) navigates between next/prev fold
" to not throw me off with scrolling, which is what z(h/l) did originally
nnoremap zl zr
nnoremap zL zR
nnoremap zh <Nop>

" mappings during insert mode
" when using C-u/C-w in insert mode, create a new change instead of appending
inoremap <C-u> <C-g>u<C-u>
inoremap <C-w> <C-g>u<C-w>
" escape while in insert-mode
inoremap jj <Esc>
" insert newline without going into insert-mode
nnoremap <CR> o<Esc>
" insert timestamp in place; TODO what is this <C-R>?
iabbrev YTS <C-R>=Timestamp()<CR>

" copy and paste to global clipboard using leader key
"nnoremap <Leader>v "+p
"vnoremap <Leader>v "+p
nnoremap <Leader>v <Leader>tp"+p<Leader>tp
vnoremap <Leader>v <Leader>tp"+p<Leader>tp
nnoremap <Leader>c "+yy
vnoremap <Leader>c "+y
vnoremap <Leader>x "+d

" do :ls before switching buffers
nnoremap <Leader>b :ls<CR>:b

" split vertically and horizontally
" C-w s/v already exist for these two cases
"nnoremap <Leader>v :vsplit<CR>
"nnoremap <Leader>h :split<CR>

nnoremap <C-a> <Nop>
nnoremap <C-x> <Nop>

" Toggle different modes
" syntax, diff, paste, wrap, listchars, highlight, and scrollbind. Missing anything?
nnoremap <Leader>ts :call ToggleSyntax()<CR>
nnoremap <Leader>td :call ToggleDiff()<CR>
set pastetoggle=,tp
nnoremap <Leader>tw :set wrap!<CR>
nnoremap <Leader>tl :set list!<CR>
" add a second <C-l> after <CR> to redraw the screen
nnoremap <C-l> :set hlsearch!<CR>
nnoremap <Leader>tb :set scrollbind!<CR>
" TODO kind of incomplete?
"nnoremap <Leader>tc :setlocal invspell spellang=en_us<CR>
" }}}

" Plugin Maps {{{

" CtrlP is pretty hawsome
let g:ctrlp_user_command = {
    \ 'types': {
        \ 1: ['.git', 'cd %s && git ls-files'],
        \ 2: ['.hg', 'hg --cwd %s locate -I .'],
        \ },
    \ 'fallback': 'find %s -type f'
    \ }

let g:neocomplete#enable_at_startup = 1
let g:tagbar_autofocus = 1
let g:indent_guides_auto_colors = 0
let g:indent_guides_guide_size = 1
autocmd VimEnter,Colorscheme * :hi IndentGuidesOdd  guibg=red   ctermbg=black
autocmd VimEnter,Colorscheme * :hi IndentGuidesEven guibg=green ctermbg=darkgrey

nnoremap <Leader>gg :GundoToggle<CR>
nnoremap <Leader>dd :TagbarToggle<CR>
nnoremap <Leader>ff :CtrlPBuffer<CR>
nnoremap <Leader>aa :NERDTreeToggle<CR>
nnoremap <Leader>ii :IndentGuidesToggle<CR>
nnoremap <Leader>ss :Ack 
" trailing space on <Leader>ss intentional

" }}}

" TODO {{{
" http://stackoverflow.com/questions/63104/smarter-vim-recovery
" or some better recovery method.

" }}}

" vim:fdm=marker:fdl=1
