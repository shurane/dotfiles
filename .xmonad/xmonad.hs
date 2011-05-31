import XMonad
import XMonad.Hooks.DynamicLog
import XMonad.Hooks.ManageDocks
import XMonad.Hooks.ManageHelpers
import XMonad.Util.Run(spawnPipe)
import XMonad.Util.EZConfig(additionalKeysP,removeKeysP)
import qualified XMonad.StackSet as W

import XMonad.Config.Gnome
import XMonad.Layout.NoBorders

import System.IO

-- windows that float
myManageHook = composeAll 
    [
        className =? "Pidgin"           --> doFloat
      , className =? "Gnome-panel"      --> doFloat
      , className =? "SMplayer"         --> doFloat
      , className =? "Xmessage"         --> doF W.shiftMaster <+> doCenterFloat
      , className =? "Do"               --> doFloat
    ] 

bindKeys = 
    [
        -- bind M-r to dmenu
        -- bind M-Print to take a snapshot
        -- bind M-p to previous window
        -- bind M-n to next window
        ("M-r",         spawn "exe=$(dmenu_path | dmenu -i) && eval \"exec $exe\"")
      , ("M-p",         windows W.focusUp)
      , ("M-n",         windows W.focusDown)
      , ("M-S-p",       windows W.swapUp)
      , ("M-S-n",       windows W.swapDown)
      , ("M-<Print>",   spawn "scrot")
      , ("M-<F2>",      spawn "gmrun")
      , ("M-;",         spawn "xprop | grep WM_CLASS | xmessage -file -")
      , ("M-s",         refresh)
    ]

unbindKeys = 
    [
        ("M-j")
      , ("M-k")
    ]

conf = gnomeConfig 
    {
        modMask = mod4Mask
      , focusFollowsMouse = False
      , terminal = "gnome-terminal"
      , manageHook = manageDocks 
                 <+> myManageHook 
                 <+> manageHook gnomeConfig
      , layoutHook = smartBorders (layoutHook gnomeConfig)
--       , logHook = dynamicLogWithPP xmobarPP
--                     { ppOutput = hPutStrLn xmproc
--                     , ppTitle = xmobarColor "green" "" . shorten 50
--                     }
    } `additionalKeysP` bindKeys `removeKeysP` unbindKeys

main = do
--     xmproc <- spawnPipe "xmobar"
    xmonad conf
