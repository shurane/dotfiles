import XMonad
import qualified XMonad.StackSet as W
import qualified Data.Map as M

import XMonad.Util.Run(spawnPipe)
import XMonad.Util.EZConfig(additionalKeysP,removeKeysP)


import XMonad.Actions.FloatKeys
import XMonad.Actions.GridSelect

import XMonad.Hooks.DynamicLog
import XMonad.Hooks.ManageDocks
import XMonad.Hooks.ManageHelpers

import XMonad.Layout.NoBorders
import XMonad.Layout.ResizableTile
import XMonad.Layout.Named
import XMonad.Layout.Tabbed

import XMonad.Config.Gnome

import System.IO
import Data.Ratio

myManageHook = composeAll 
    [
      isFullscreen                          --> doFullFloat
    , className =? "Pidgin"                 --> doFloat
    ,     title =? "Buddy List"             --> doFloat
  --, className =? "Gnome-panel"            --> doFloat
    , className =? "SMplayer"               --> doFloat
    , className =? "Xmessage"               --> doF W.shiftMaster <+> doCenterFloat
    , className =? "Do"                     --> doFloat
    , className =? "Gmrun"                  --> doF W.shiftMaster <+> doCenterFloat
    ,     title =? "Downloads"              --> doF W.shiftMaster <+> doCenterFloat
    ,     title =? "Firefox Preferences"    --> doF W.shiftMaster <+> doCenterFloat
    ,     title =? "Xchat: Network List"    --> doF W.shiftMaster <+> doCenterFloat
    ] 

bindKeys = 
    [
      -- bind M-r to dmenu
      -- bind M-Print to take a snapshot
      -- bind M-p to previous window
      -- bind M-n to next window
      -- bind M-(S)-(-/=) to resize window a variety of ways -- maybe I'll get aspect ratio preserving later
      ("M-S-;",       spawn "exe=$(dmenu_path | dmenu -i) && eval \"exec $exe\"")
    , ("M-q",         spawn "xmonad --recompile && xmonad --restart")
    , ("M-b",         sendMessage ToggleStruts)
    , ("M-p",         windows W.focusUp)
    , ("M-n",         windows W.focusDown)
    , ("M-S-p",       windows W.swapUp)
    , ("M-S-n",       windows W.swapDown)
    , ("M-g",         goToSelected defaultGSConfig) 
    , ("M-<Print>",   spawn "scrot -e 'mv $f ~/Pictures/screenshots/'")
    , ("M-<F2>",      spawn "gmrun")
    , ("M-;",         spawn "xprop | grep -E \"^WM_CLASS|^WM_NAME\" | xmessage -file -")
    , ("M-s",         refresh)
    , ("M-=",         withFocused (keysResizeWindow ( 10,  10) (1/2, 1/2))) 
    , ("M--",         withFocused (keysResizeWindow (-10, -10) (1/2, 1/2)))
    , ("M-S--",       withFocused (keysResizeWindow (  0, -10) (  0,   0)))     
    , ("M-S-=",       withFocused (keysResizeWindow (  0,  10) (  0,   0))) 
    ]

unbindKeys = 
    [
      ("M-j")
    , ("M-k")
    ]

customPP = defaultPP 
    { ppCurrent = xmobarColor "#429942" "" . wrap "<" ">"
    , ppHidden = xmobarColor "#C98F0A" ""
    , ppHiddenNoWindows = xmobarColor "#C9A34E" ""
    , ppUrgent = xmobarColor "#FFFFAF" "" . wrap "[" "]" 
    , ppLayout = xmobarColor "#C9A34E" ""
    , ppTitle =  xmobarColor "#C9A34E" "" . shorten 80
    , ppSep = xmobarColor "#429942" "" " | "
    }

tabTheme1 = defaultTheme { decoHeight = 16
                         , activeColor = "#a6c292"
                         , activeBorderColor = "#a6c292"
                         , activeTextColor = "#000000"
                         , inactiveBorderColor = "#000000"
                         }

myLayoutHook = avoidStrutsOn [] $ tall ||| wide ||| tab ||| full
    where
        rt      = ResizableTall 1 (2/100) (1/2) []
        rw      = ResizableWide 1 (2/100) (1/2) []
        tall    = named "[T]=" $ smartBorders rt
        wide    = named "[W]=" $ smartBorders rw
        tab     = named "+" $ noBorders $ tabbed shrinkText tabTheme1
        full    = named "[]" $ noBorders Full

conf = gnomeConfig 
    {
      modMask = mod4Mask
    , focusFollowsMouse = False
    , terminal = "gnome-terminal"
    , manageHook = manageDocks 
               <+> myManageHook 
               <+> manageHook gnomeConfig
    , layoutHook = myLayoutHook
    , borderWidth = 1
    , normalBorderColor = "#333333"
    , focusedBorderColor = "#AFAF87"
    } `additionalKeysP` bindKeys `removeKeysP` unbindKeys

main = do
--     xmproc <- spawnPipe "xmobar"
    xmonad conf
