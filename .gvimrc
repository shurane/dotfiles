" GVim Settings {{{
" maybe i'll relocate it to .gvimrc later
    set novisualbell 
    set t_vb=
    set guioptions=Aci
    map <F3> <Esc>:set guifont=*<CR>
    set lines=40
    "colorscheme wombat256mod
    " Win32 Settings {{{
    if has('win32')
        set guifont=Consolas:h10:cANSI
    elseif has('unix')
        set guifont=Ubuntu\ Mono\ 12
    endif
    " }}}

" }}}


