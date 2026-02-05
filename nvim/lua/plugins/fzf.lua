return {
  -- fzf binary
  {
    "junegunn/fzf",
    build = "./install --bin",
  },

  -- fzf-lua
  {
    "ibhagwan/fzf-lua",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
      "<C-p>",
      "<leader>fg",
      "<leader>ff",
      "<leader>fb",
      "<leader>f/",
      "<leader>fh",
      "<leader>fo",
      "<leader>fl",
      "<leader>fs",
    },
    config = function()
      local fzf = require("fzf-lua")
      fzf.setup({
        winopts = {
          height = 0.95,
          width = 0.95,
          preview = {
            default = "builtin",
            border = "border",
            wrap = "nowrap",
            hidden = "nohidden",
          },
        },
        files = {
          git_icons = true,
          file_icons = true,
          fd_opts = "--color=never --type f --hidden --follow --exclude .git",
        },
      })

      -- Keybindings
      vim.keymap.set("n", "<C-p>", fzf.files, { desc = "Find files" })
      vim.keymap.set("n", "<leader>fg", fzf.live_grep, { desc = "Grep" })
      vim.keymap.set("n", "<leader>fs", function() fzf.blines({ hls = { cursorline = "IncSearch"}}) end, { desc = "Grep current buffer" })
      vim.keymap.set("n", "<leader>ff", function() fzf.lines({ hls = { cursorline = "IncSearch"}}) end, { desc = "Grep open buffers" })
      vim.keymap.set("n", "<leader>fb", fzf.buffers, { desc = "Search buffer names" })
      vim.keymap.set("n", "<leader>fh", fzf.help_tags, { desc = "Help tags" })
      vim.keymap.set("n", "<leader>fo", fzf.oldfiles, { desc = "Old files" })
      vim.keymap.set("n", "<leader>fr", fzf.lsp_references, { desc = "LSP references" })
      vim.keymap.set("n", "<leader>fl", fzf.lsp_document_symbols, { desc = "LSP document symbols" })
      vim.keymap.set("n", "<leader>fw", fzf.lsp_workspace_symbols, { desc = "LSP workspace symbols" })
    end,
  },
}
