return {
  -- nvim-web-devicons
  {
    "nvim-tree/nvim-web-devicons",
    lazy = true,
  },

  -- barbar.nvim
  {
    "romgrk/barbar.nvim",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    event = "VeryLazy",
    keys = {
      { "<C-h>", "<cmd>BufferPrevious<CR>", desc = "Previous buffer" },
      { "<C-l>", "<cmd>BufferNext<CR>", desc = "Next buffer" },
      { "<leader>bc", "<cmd>BufferClose<CR>", desc = "Close buffer" },
      { "<leader>bw", "<cmd>BufferWipeout<CR>", desc = "Wipeout buffer" },
    },
    config = function()
      require("barbar").setup({
        auto_hide = true,
      })
    end,
  },

  -- which-key.nvim
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    keys = {
      { "<leader><leader>", "<cmd>WhichKey<CR>", desc = "Show all keymaps" },
    },
    config = function()
      require("which-key").setup()
    end,
  },

  -- trouble.nvim
  {
    "folke/trouble.nvim",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
      { "<leader>xx", "<cmd>Trouble diagnostics toggle<CR>", desc = "Diagnostics (Trouble)" },
      { "<leader>xX", "<cmd>Trouble diagnostics toggle filter.buf=0<CR>", desc = "Buffer Diagnostics (Trouble)" },
      { "<leader>cs", "<cmd>Trouble symbols toggle focus=false<CR>", desc = "Symbols (Trouble)" },
      { "<leader>cl", "<cmd>Trouble lsp toggle focus=false win.position=right<CR>", desc = "LSP (Trouble)" },
      { "<leader>xL", "<cmd>Trouble loclist toggle<CR>", desc = "Location List (Trouble)" },
      { "<leader>xQ", "<cmd>Trouble qflist toggle<CR>", desc = "Quickfix List (Trouble)" },
    },
    config = function()
      require("trouble").setup({})
    end,
  },

  -- Colorscheme
  {
    "olimorris/onedarkpro.nvim",
    lazy = false,
    priority = 1000,
    config = function()
      require("onedarkpro").setup()
      vim.cmd([[colorscheme onedark_dark]])
    end,
  },
  -- Other popular colorschemes (uncomment to use):
  -- { "catppuccin/nvim", name = "catppuccin", priority = 1000 },
  -- { "folke/tokyonight.nvim", priority = 1000 },
  -- { "rose-pine/neovim", name = "rose-pine", priority = 1000 },
  -- { "EdenEast/nightfox.nvim", priority = 1000 },
  -- { "rebelot/kanagawa.nvim", priority = 1000 },
}
