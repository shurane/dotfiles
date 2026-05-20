return {
  {
    "nvim-treesitter/nvim-treesitter",
    branch = "main",
    build = ":TSUpdate",
    event = { "BufReadPost", "BufNewFile" },
    cmd = { "TSInstall", "TSUpdate", "TSUninstall", "TSInstallFromGrammar", "TSLog" },
    config = function()
      require("nvim-treesitter").setup()
      vim.treesitter.language.register("json", "jsonc")
      require("nvim-treesitter").install({
        -- "java",
        -- "rust",
        "cpp",
        "python",
        "javascript",
        "typescript",
        "tsx",
        "json",
        "bash",
        "markdown",
        "vim",
        "lua",
      })
      vim.api.nvim_create_autocmd("FileType", {
        callback = function(args)
          local ok = pcall(vim.treesitter.start, args.buf)
          if ok then
            vim.bo[args.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
          end
        end,
      })
    end,
  },
}
