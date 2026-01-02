set nocp
set number
set ts=4
set sts=4
set sw=4
set expandtab
set bs=2
set scrolloff=3
set incsearch
set ignorecase
set linebreak
set pastetoggle=,tp
set directory=$HOME/.vim/swapfiles/
set lcs=trail:-,extends:>,tab:>-,eol:$
set vb t_vb=
set splitright
set signcolumn=number
set updatetime=300
let mapleader = ","

" Basic mappings
inoremap jj <Esc>
nnoremap j gj
nnoremap k gk
nnoremap <C-s> :set hlsearch!<CR>
nnoremap <Leader>tw :set wrap!<CR>
nnoremap <Leader>tl :set list!<CR>
nnoremap <CR> o<Esc>
nnoremap <Leader>eev :e $HOME/.vimrc<CR>
nnoremap <Leader>ev :e $MYVIMRC<CR>
nnoremap <Leader>sv :source $MYVIMRC<CR>
vnoremap < <gv
vnoremap > >gv

" https://github.com/junegunn/vim-plug
" Automatic installaion of vim-plug and swapfiles creation
if empty(glob('~/.vim/autoload/plug.vim'))
  silent !mkdir -p ~/.vim/swapfiles
  silent !mkdir -p ~/.vim/autoload
  silent !curl -fLo ~/.vim/autoload/plug.vim
    \ https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
  autocmd VimEnter * PlugInstall
endif

call plug#begin('~/.vim/plugged')
  " Fuzzy finding
  Plug 'junegunn/fzf'
  Plug 'junegunn/fzf.vim'

  " Editing enhancements
  Plug 'tpope/vim-commentary'
  Plug 'tpope/vim-surround'
  Plug 'jiangmiao/auto-pairs'
  Plug 'ntpeters/vim-better-whitespace'
  Plug 'tpope/vim-repeat'
  Plug 'tpope/vim-eunuch'
  Plug 'lambdalisue/suda.vim'

  " Git integration
  Plug 'tpope/vim-fugitive'
  Plug 'airblade/vim-gitgutter'

  " File management
  Plug 'tpope/vim-vinegar'

  " UI enhancements
  Plug 'ryanoasis/vim-devicons'
  Plug 'ap/vim-buftabline'
  Plug 'liuchengxu/vim-which-key'

  " LSP and linting
  Plug 'prabirshrestha/async.vim'
  Plug 'prabirshrestha/vim-lsp'
  Plug 'mattn/vim-lsp-settings'
  Plug 'prabirshrestha/asyncomplete.vim'
  Plug 'prabirshrestha/asyncomplete-lsp.vim'
  Plug 'dense-analysis/ale'

  " Colorschemes
  Plug 'EvitanRelta/vim-colorschemes'
  "Plug 'navarasu/onedark.nvim'
  "Plug 'sainnhe/sonokai'
  "Plug 'rktjmp/lush.nvim'
  "Plug 'ViViDboarder/wombat.nvim'
  "Plug 'Mofiqul/vscode.nvim'
  "Plug 'EdenEast/nightfox.nvim'
  "Plug 'tiagovla/tokyodark.nvim'
call plug#end()

" Plugin settings
let g:vim_markdown_folding_disabled = 1
let g:vim_markdown_new_list_item_indent = 0
let g:suda_smart_edit = 1

" Colorscheme
colorscheme onedark
highlight Normal guibg=black guifg=white

if has('termguicolors')
  set termguicolors
endif

" fzf.vim settings
let g:fzf_layout = { 'window': { 'width': 0.8, 'height': 0.85, 'border': 'rounded' } }
let g:fzf_preview_window = ['right:50%', 'ctrl-/']

" fzf.vim keybindings
nnoremap <C-p> :Files<CR>
nnoremap <leader>fg :Rg<CR>
nnoremap <leader>fb :Buffers<CR>
nnoremap <leader>fh :Helptags<CR>
nnoremap <leader>fo :History<CR>
nnoremap <leader>fl :BTags<CR>
nnoremap <leader>fs :Tags<CR>

" Buffer navigation
nnoremap <C-h> :bprevious<CR>
nnoremap <C-l> :bnext<CR>
nnoremap <Leader>bc :bd<CR>
nnoremap <Leader>bw :bw<CR>

" ALE diagnostics
nnoremap <leader>xx :lopen<CR>
nnoremap <leader>xc :lclose<CR>
nnoremap <leader>xq :copen<CR>
nnoremap [d :ALEPreviousWrap<CR>
nnoremap ]d :ALENextWrap<CR>

" vim-which-key
nnoremap <leader><leader> :WhichKey ','<CR>

" vim-vinegar uses - by default for netrw

" vim-lsp configuration
function! s:on_lsp_buffer_enabled() abort
  setlocal omnifunc=lsp#complete
  setlocal signcolumn=yes
  nmap <buffer> gd <plug>(lsp-definition)
  nmap <buffer> gr <plug>(lsp-references)
  nmap <buffer> gi <plug>(lsp-implementation)
  nmap <buffer> gt <plug>(lsp-type-definition)
  nmap <buffer> K <plug>(lsp-hover)
  nmap <buffer> <leader>rn <plug>(lsp-rename)
  nmap <buffer> <leader>ca <plug>(lsp-code-action)
  nmap <buffer> <leader>ld <plug>(lsp-document-diagnostics)
endfunction

augroup lsp_install
  au!
  autocmd User lsp_buffer_enabled call s:on_lsp_buffer_enabled()
augroup END

" vim-lsp settings
let g:lsp_diagnostics_enabled = 1
let g:lsp_diagnostics_echo_cursor = 1
let g:lsp_diagnostics_float_cursor = 1
let g:lsp_document_highlight_enabled = 1

" asyncomplete settings
let g:asyncomplete_auto_popup = 1
let g:asyncomplete_auto_completeopt = 0
set completeopt=menuone,noinsert,noselect,preview
inoremap <expr> <Tab> pumvisible() ? "\<C-n>" : "\<Tab>"
inoremap <expr> <S-Tab> pumvisible() ? "\<C-p>" : "\<S-Tab>"
inoremap <expr> <CR> pumvisible() ? asyncomplete#close_popup() : "\<CR>"

" Register LSP servers (vim-lsp-settings will auto-install)
if executable('clangd')
  au User lsp_setup call lsp#register_server({
    \ 'name': 'clangd',
    \ 'cmd': {server_info->['clangd']},
    \ 'allowlist': ['c', 'cpp', 'objc', 'objcpp'],
    \ })
endif

if executable('pyright-langserver')
  au User lsp_setup call lsp#register_server({
    \ 'name': 'pyright',
    \ 'cmd': {server_info->['pyright-langserver', '--stdio']},
    \ 'allowlist': ['python'],
    \ })
endif

if executable('typescript-language-server')
  au User lsp_setup call lsp#register_server({
    \ 'name': 'typescript-language-server',
    \ 'cmd': {server_info->['typescript-language-server', '--stdio']},
    \ 'allowlist': ['javascript', 'javascriptreact', 'typescript', 'typescriptreact'],
    \ })
endif

" ALE configuration
let g:ale_linters = {
\   'python': ['ruff'],
\   'javascript': ['eslint'],
\   'typescript': ['eslint'],
\}
let g:ale_fixers = {
\   '*': ['remove_trailing_lines', 'trim_whitespace'],
\   'python': ['ruff'],
\   'javascript': ['prettier'],
\   'typescript': ['prettier'],
\}
let g:ale_fix_on_save = 0
let g:ale_sign_error = 'E'
let g:ale_sign_warning = 'W'

" vim-gitgutter configuration
let g:gitgutter_sign_added = '+'
let g:gitgutter_sign_modified = '~'
let g:gitgutter_sign_removed = '_'
let g:gitgutter_sign_removed_first_line = '‾'
let g:gitgutter_sign_modified_removed = '~'
nmap ]c <Plug>(GitGutterNextHunk)
nmap [c <Plug>(GitGutterPrevHunk)
nmap <leader>hs <Plug>(GitGutterStageHunk)
nmap <leader>hr <Plug>(GitGutterUndoHunk)
nmap <leader>hp <Plug>(GitGutterPreviewHunk)

" vim-better-whitespace
let g:better_whitespace_enabled = 1
let g:strip_whitespace_on_save = 0

" vim-buftabline
let g:buftabline_show = 1
let g:buftabline_numbers = 1

" vim-which-key
let g:which_key_map = {}
call which_key#register(',', "g:which_key_map")

" Bigfile handling (disable features for large files)
augroup bigfile
  au!
  autocmd BufReadPre * if getfsize(expand('%')) > 1048576 |
    \ setlocal noswapfile |
    \ setlocal bufhidden=unload |
    \ setlocal undolevels=-1 |
    \ setlocal foldmethod=manual |
    \ setlocal nofoldenable |
    \ endif
augroup END
