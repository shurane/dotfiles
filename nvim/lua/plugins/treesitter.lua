return {
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
    event = { "BufReadPost", "BufNewFile" },
    config = function()
      require("nvim-treesitter.configs").setup({
        ensure_installed = {
          "java",
          "cpp",
          "rust",
          "python",
          "javascript",
          "jsonc",
          "typescript",
          "tsx",
          "bash",
          "markdown",
          "vim",
          "lua",
        },
        highlight = {
          enable = true,
          additional_vim_regex_highlighting = "vim",
        },
        incremental_selection = {
          enable = true,
          keymaps = {
            init_selection = "gnn",
            node_incremental = "grn",
            scope_incremental = "grc",
            node_decremental = "grm",
          },
        },
      })
    end,
  },
}
