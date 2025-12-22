return {
  -- Comment.nvim
  {
    "numToStr/Comment.nvim",
    keys = {
      { "gc", mode = { "n", "v" }, desc = "Comment toggle" },
      { "gb", mode = { "n", "v" }, desc = "Comment toggle blockwise" },
      { "<leader>cc", mode = { "n", "v" }, desc = "Comment" },
      { "<leader>cu", mode = { "n", "v" }, desc = "Uncomment" },
      { "<leader>c<space>", mode = { "n", "v" }, desc = "Toggle" },
    },
    config = function()
      local api = require("Comment.api")
      require("Comment").setup()

      -- Custom keybindings for old nerdcommenter style
      vim.keymap.set("n", "<leader>cc", api.comment.linewise.current, { desc = "Comment line" })
      vim.keymap.set("n", "<leader>cu", api.uncomment.linewise.current, { desc = "Uncomment line" })
      vim.keymap.set("n", "<leader>c<space>", api.toggle.linewise.current, { desc = "Toggle line" })

      -- Send ESC to update the marks '< and '>, then call the API
      vim.keymap.set("x", "<leader>cc", function()
        vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<ESC>", true, false, true), "nx", false)
        api.comment.linewise(vim.fn.visualmode())
      end, { desc = "Comment selection" })

      vim.keymap.set("x", "<leader>cu", function()
        vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<ESC>", true, false, true), "nx", false)
        api.uncomment.linewise(vim.fn.visualmode())
      end, { desc = "Uncomment selection" })

      vim.keymap.set("x", "<leader>c<space>", function()
        vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<ESC>", true, false, true), "nx", false)
        api.toggle.linewise(vim.fn.visualmode())
      end, { desc = "Toggle selection" })

    end,
  },

  -- oil.nvim
  {
    "stevearc/oil.nvim",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
      { "-", "<cmd>Oil<CR>", desc = "Open parent directory" },
    },
    config = function()
      require("oil").setup({
        default_file_explorer = true,
        columns = {
          "icon",
          "permissions",
          "size",
          "mtime",
        },
        view_options = {
          show_hidden = false,
        },
        keymaps = {
          ["g?"] = "actions.show_help",
          ["<CR>"] = "actions.select",
          ["<C-v>"] = "actions.select_vsplit",
          ["<C-x>"] = "actions.select_split",
          ["<C-t>"] = "actions.select_tab",
          ["<C-p>"] = "actions.preview",
          ["<C-c>"] = "actions.close",
          ["<C-l>"] = "actions.refresh",
          ["-"] = "actions.parent",
          ["_"] = "actions.open_cwd",
          ["`"] = "actions.cd",
          ["~"] = "actions.tcd",
          ["gs"] = "actions.change_sort",
          ["gx"] = "actions.open_external",
          ["g."] = "actions.toggle_hidden",
        },
      })
    end,
  },

  {
    "echasnovski/mini.nvim",
    config = function()
      require("mini.trailspace").setup()
      -- Trim whitespace on save
      vim.api.nvim_create_autocmd("BufWritePre", {
        pattern = "*",
        callback = function()
          require("mini.trailspace").trim()
        end,
      })
    end,
  },
  { "lambdalisue/suda.vim", lazy = false, init = function() vim.g.suda_smart_edit = 1 end, },
  { "kylechui/nvim-surround", event = "VeryLazy", config = function() require("nvim-surround").setup() end, },
  { "windwp/nvim-autopairs", event = "InsertEnter", config = function() require("nvim-autopairs").setup() end, },
  { "tpope/vim-repeat", event = "VeryLazy", },
  { "tpope/vim-eunuch", cmd = { "Remove", "Delete", "Move", "Rename", "Chmod", "Mkdir" }, },
  { "LunarVim/bigfile.nvim", event = { "BufReadPre", "BufNewFile" }, },
}
