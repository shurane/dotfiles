local is_root = (vim.env.USER == "root")
local home = vim.fn.expand("~" .. (vim.env.SUDO_USER or vim.env.USER))
local lazy_dir = home .. "/.local/share/nvim/lazy"

-- Bootstrap lazy.nvim
local lazypath = lazy_dir .. "/lazy.nvim"
if not is_root and not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable",
    lazypath,
  })
end
vim.opt.runtimepath:prepend(lazypath)

-- Setup lazy.nvim
require("lazy").setup("plugins", {
  root = lazy_dir,
  change_detection = {
    notify = false,
    enabled = not is_root,
  },
  install = { missing = not is_root },
  rocks = { enabled = not is_root },
  pkg = { enabled = not is_root },
})

-- Block mutating lazy commands as root
if is_root then
  local blocked = { "install", "update", "sync", "clean", "restore", "build" }
  for _, cmd in ipairs(blocked) do
    require("lazy")[cmd] = function()
      vim.notify("Lazy " .. cmd .. " disabled as root", vim.log.levels.WARN)
    end
  end
end
