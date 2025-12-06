return {
  -- fzf binary
  {
    "junegunn/fzf",
    build = "./install --all",
  },

  -- fzf-lua
  {
    "ibhagwan/fzf-lua",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
      { "<C-p>", "<cmd>lua require('fzf-lua').files()<CR>", desc = "Find files" },
      { "<leader>fg", "<cmd>lua require('fzf-lua').live_grep()<CR>", desc = "Live grep" },
      { "<leader>fb", "<cmd>lua require('fzf-lua').buffers()<CR>", desc = "Buffers" },
      { "<leader>fh", "<cmd>lua require('fzf-lua').help_tags()<CR>", desc = "Help tags" },
      { "<leader>fo", "<cmd>lua require('fzf-lua').oldfiles()<CR>", desc = "Old files" },
      { "<leader>fl", "<cmd>lua require('fzf-lua').lsp_document_symbols()<CR>", desc = "LSP document symbols" },
      { "<leader>fs", "<cmd>lua require('fzf-lua').lsp_workspace_symbols()<CR>", desc = "LSP workspace symbols" },
    },
    config = function()
      require("fzf-lua").setup({
        winopts = {
          height = 0.85,
          width = 0.80,
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
    end,
  },
}
