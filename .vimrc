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
"colorscheme wombat256mod    " nice dark theme
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
filetype indent on          " indent depends on filetype
filetype plugin on          " enable plugins
syntax enable               " Syntax highlighting

"if has('persistent_undo')
    "set undofile            " Enable persistent undo
    "set undodir=~/.vim/undo " Store undofiles in a tmp dir
"endif

set cpoptions=yraABceFq
set formatoptions+=tcq
" this formatoption isn't working, it seems
set formatoptions-=r        " don't insert comment after <CR>

" }}}

" Syntax Setup {{{

autocmd BufRead,BufNewFile *.txt setfiletype text
autocmd FileType text set wrap
"autocmd FileType cpp set makeprg=clang\ -g\ %\ -o\ %<.out

highlight SpellBad term=underline gui=undercurl guisp=Orange 
autocmd FileType python set makeprg=pylint\ --reports=n\ --output-format=parseable\ %:p
autocmd FileType python set errorformat=%f:%l:\ %m

let python_highlight_all=1
"set tags+=tags

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

" VAM for plugin management -- consider moving to gmarik/vundle -- seems easier
" after setting this up
function! ActivateVAM()
    let addons_base = expand('$HOME') . '/vim-addons'
    let addons_manager = addons_base . '/vim-addon-manager'
    execute 'set runtimepath+=' . addons_manager

    if finddir(addons_base, '') == ''
        call mkdir(addons_base, '')
    endif
    if finddir(addons_manager) == ''
        execute 'cd ' . addons_base
        execute '!git clone git://github.com/MarcWeber/vim-addon-manager.git'
    endif
endfunction


" }}}

" Vim Maps {{{

let mapleader = ","

" swap keys TODO what is this?
nnoremap ' `
nnoremap ` '

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

" switch back and forth between buffers
nnoremap `n :bn<CR>
nnoremap `p :bp<CR>
" switch back and forth between tabs
nnoremap <C-n> gt<CR>
nnoremap <C-p> gT<CR>

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
" insert timestamp in place
iabbrev YTS <C-R>=Timestamp()<CR>

" copy and paste to global clipboard using leader key
"nnoremap <Leader>v "+p
"vnoremap <Leader>v "+p
nnoremap <Leader>v ,tp"+p,tp
vnoremap <Leader>v ,tp"+p,tp
nnoremap <Leader>c "+yy
vnoremap <Leader>c "+y

" do :ls before switching buffers
"nnoremap <Leader>b :ls<CR>:b


" split vertically and horizontally
" C-w s/v already exist for these two cases
"nnoremap <Leader>v :vsplit<CR>
"nnoremap <Leader>h :split<CR>

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

" shortcuts for tmux integration
nnoremap <silent> <C-w>h :call TmuxWindowMotion('h')<CR>
nnoremap <silent> <C-w>j :call TmuxWindowMotion('j')<CR>
nnoremap <silent> <C-w>k :call TmuxWindowMotion('k')<CR>
nnoremap <silent> <C-w>l :call TmuxWindowMotion('l')<CR>

" }}}

" Plugin Setup {{{

" lots of ideas from talek

call ActivateVAM()

let g:vim_addon_manager = {'known_repos_activation_policy' : 'autoload', 'auto_install' : 1}
let g:vim_addon_manager.plugin_sources = {}
let g:vim_addon_manager.plugin_sources['nerd_commenter'] = {'type': 'git', 'url': 'git://github.com/scrooloose/nerdcommenter.git'}
let g:vim_addon_manager.plugin_sources['nerdtree'] = {'type': 'git', 'url': 'git://github.com/scrooloose/nerdtree.git'}
let g:vim_addon_manager.plugin_sources['surround'] = {'type': 'git', 'url': 'git://github.com/tpope/vim-surround.git'}
let g:vim_addon_manager.plugin_sources['repeat'] = {'type': 'git', 'url': 'git://github.com/tpope/vim-repeat.git'}

let g:addons = [ 'nerd_commenter', 'surround', 'repeat', 'Gundo', 'taglist', 'fugitive', 'FuzzyFinder' ] 
"others: pylint, pyflakes2441, nerdtree

call vam#ActivateAddons(addons)

" }}}

" Plugin Maps {{{

" shortcuts for NERDTree
let NERDTreeMapActivateNode='<CR>'
nnoremap <Leader>tt :NERDTreeToggle<CR>

" shortcuts for Taglist and Tags in general
"let Tlist_Ctags_Cmd = "ctags"
let Tlist_GainFocus_On_ToggleOpen = 1
let Tlist_Exit_OnlyWindow = 1
nnoremap <Leader>dr :!ctags --recurse --fields=+iaS --extra=+q .<CR>
nnoremap <C-\> :tab split<CR>:exec("tag ".expand("<cword>"))<CR>
nnoremap <Leader>dd :TlistToggle<CR>
"nnoremap <Leader>dd :TlistOpen<CR>
"nnoremap <Leader>dc :TlistClose<CR>


" idea for <Leader>do: Tlist_Show_One_File toggle
" change this so it only opens a new split if there is a tag for the word
"nnoremap <A-]> :vsp <CR>:exec("tag ".expand("<cword>"))<CR>

" shortcuts for Gundo
nnoremap <Leader>gg :GundoToggle<CR>

" shortcuts for FuzzyFinder
nnoremap <Leader>f :FufFileWithCurrentBufferDir<CR>
nnoremap <Leader>b :FufBuffer<CR>

" unmappings from various plugins
silent! nunmap \tt
silent! nunmap dd

" }}}

" TODO List {{{
    " Fix up mappings, definitely
    " determine if switch between VAM and vundle is necessary
    " cscope setup
    " language-specific addons only turned on when dealing with said language
    " error formats for makeprg would be great for C++

" }}}


" vim:fdm=marker:fdl=1
"
