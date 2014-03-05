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

    function! EnlargeFont()
        let l:font=split( &guifont )
        let l:font[-1] = l:font[-1] + 1
        let &guifont=join( l:font, ' ' )
    endfunction

    function! ShrinkFont()
        let l:font=split( &guifont )
        if l:font[-1] > 2 
            let l:font[-1] = l:font[-1] - 1
            let &guifont=join( l:font, ' ' )
        endif
    endfunction

    inoremap <C-kPlus>  <ESC>:call EnlargeFont()<CR>i
    nnoremap <C-kPlus>  :call EnlargeFont()<CR>

    inoremap <C-kMinus> <ESC>:call ShrinkFont()<CR>i
    nnoremap <C-kMinus> :call ShrinkFont()<CR>

" }}}


