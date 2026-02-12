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
    lazy = false,
    config = function()
      require("barbar").setup({
        auto_hide = true,
      })

      -- Keybindings
      vim.keymap.set("n", "<C-h>", "<cmd>BufferPrevious<CR>", { desc = "Previous buffer" })
      vim.keymap.set("n", "<C-l>", "<cmd>BufferNext<CR>", { desc = "Next buffer" })
      vim.keymap.set("n", "<leader>bc", "<cmd>BufferClose<CR>", { desc = "Close buffer" })
      vim.keymap.set("n", "<leader>bw", "<cmd>BufferWipeout<CR>", { desc = "Wipeout buffer" })
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
      "<leader>xx",
      "<leader>xX",
      "<leader>cs",
      "<leader>cl",
      "<leader>xL",
      "<leader>xQ",
    },
    config = function()
      local trouble = require("trouble")
      trouble.setup({})

      -- Keybindings
      vim.keymap.set("n", "<leader>xx", function() trouble.toggle("diagnostics") end, { desc = "Diagnostics (Trouble)" })
      vim.keymap.set("n", "<leader>xX", function() trouble.toggle({ mode = "diagnostics", filter = { buf = 0 } }) end, { desc = "Buffer Diagnostics (Trouble)" })
      vim.keymap.set("n", "<leader>cs", function() trouble.toggle({ mode = "symbols", focus = false }) end, { desc = "Symbols (Trouble)" })
      vim.keymap.set("n", "<leader>cl", function() trouble.toggle({ mode = "lsp", focus = false, win = { position = "right" } }) end, { desc = "LSP (Trouble)" })
      vim.keymap.set("n", "<leader>xL", function() trouble.toggle("loclist") end, { desc = "Location List (Trouble)" })
      vim.keymap.set("n", "<leader>xQ", function() trouble.toggle("qflist") end, { desc = "Quickfix List (Trouble)" })
    end,
  },

  -- lualine.nvim
  {
    "nvim-lualine/lualine.nvim",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    config = function()
      local is_root = (vim.env.USER == "root")
      local sections = {
        lualine_a = { "mode" },
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { "filename" },
        lualine_x = { "encoding", "filetype" },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      }

      if is_root then
        table.insert(sections.lualine_a, 1, {
          function() return " ROOT" end,
          color = { bg = "#cc3333", fg = "#ffffff", gui = "bold" },
        })
      end

      require("lualine").setup({
        options = {
          theme = is_root and "ayu_dark" or "auto",
          section_separators = "",
          component_separators = "",
        },
        sections = sections,
      })
    end,
  },

  -- Colorscheme
  {
    "olimorris/onedarkpro.nvim",
    lazy = false,
    priority = 1000,
    config = function()
      local is_root = (vim.env.USER == "root")
      require("onedarkpro").setup({
        highlights = is_root and {
          Normal = { bg = "#1a0a0a" },
          NormalFloat = { bg = "#1a0a0a" },
          CursorLine = { bg = "#2a1010" },
          StatusLine = { bg = "#331111" },
          LineNr = { fg = "#804040" },
          CursorLineNr = { fg = "#cc5555" },
        } or {},
      })
      -- vim.cmd([[colorscheme onedark]])
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
