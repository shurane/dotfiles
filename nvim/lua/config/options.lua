-- Leader key
vim.g.mapleader = ","
vim.g.maplocalleader = ","

-- Basic settings
vim.opt.number = true
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.shiftwidth = 4
vim.opt.expandtab = true
vim.opt.backspace = "indent,eol,start"
vim.opt.scrolloff = 3
vim.opt.incsearch = true
vim.opt.ignorecase = true
vim.opt.linebreak = true
vim.opt.swapfile = true
vim.opt.directory = vim.fn.stdpath("data") .. "/swap//"
vim.opt.listchars = { trail = "-", extends = ">", tab = ">-", eol = "$" }
vim.opt.visualbell = true
vim.opt.errorbells = false
vim.opt.splitright = true
vim.opt.signcolumn = "number"
vim.opt.updatetime = 300
vim.opt.termguicolors = true

-- Create swap directory if it doesn't exist
vim.fn.mkdir(vim.fn.stdpath("data") .. "/swap", "p")
