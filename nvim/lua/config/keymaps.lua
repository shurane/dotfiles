local keymap = vim.keymap.set
local opts = { noremap = true, silent = true }

-- Basic mappings
keymap("i", "jj", "<Esc>", opts)
keymap("n", "j", "gj", opts)
keymap("n", "k", "gk", opts)
keymap("n", "<C-s>", ":set hlsearch!<CR>", opts)
keymap("n", "<Leader>tw", ":set wrap!<CR>", opts)
keymap("n", "<Leader>tl", ":set list!<CR>", opts)
keymap("n", "<CR>", "o<Esc>", opts)
keymap("n", "<Leader>ev", function()
  vim.cmd("tabnew ~/.config/nvim/init.lua")
  vim.cmd("tabnew ~/.config/nvim/lua/config/options.lua")
  vim.cmd("tabnew ~/.config/nvim/lua/config/keymaps.lua")
  vim.cmd("tabnew ~/.config/nvim/lua/config/lazy.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/editor.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/fzf.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/git.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/lsp.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/treesitter.lua")
  -- vim.cmd("tabnew ~/.config/nvim/lua/plugins/ui.lua")
  -- see also `nvimconfig` bash script that I wrote to open all these up
end, { noremap = true, silent = true, desc = "Edit nvim config" })
keymap("n", "<Leader>sv", ":source $MYVIMRC<CR>", opts)
keymap("v", "<", "<gv", opts)
keymap("v", ">", ">gv", opts)
