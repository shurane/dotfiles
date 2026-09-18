return {
  {
    "MeanderingProgrammer/render-markdown.nvim",
    ft = { "markdown" },
    dependencies = {
      "nvim-treesitter/nvim-treesitter",
      "nvim-tree/nvim-web-devicons",
    },
    keys = {
      {
        "<leader>mr",
        function()
          require("render-markdown").buf_toggle()
        end,
        desc = "Toggle Markdown rendering",
      },
      {
        "<leader>mp",
        function()
          require("render-markdown").preview()
        end,
        desc = "Markdown preview",
      },
    },
    opts = {},
  },
}
