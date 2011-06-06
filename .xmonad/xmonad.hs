import XMonad
import qualified XMonad.StackSet as W
import qualified Data.Map as M

import XMonad.Util.EZConfig(additionalKeysP,removeKeysP)
import XMonad.Util.WindowProperties (getProp32s)

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

-- spaghetti xmonad.hs!

myManageHook = (composeAll . concat $
    [ [ isFullscreen                          --> myDoFullFloat ]
    , [ className =? float                    --> doFloat                             | float  <- myFloats  ]
    , [ className =? center                   --> doF W.shiftMaster <+> doCenterFloat | center <- myCenterClasses ]
    , [     title =? center                   --> doF W.shiftMaster <+> doCenterFloat | center <- myCenterTitles ]
    , [     title =? "Buddy List"             --> doFloat ]
    ]) <+> manageTypes <+> manageDocks

    where 
        myFloats  = [ "Pidgin","SMPlayer", "Do", "Gnome-panel" ]
        myCenterClasses = [ "Xmessage", "Gmrun" ]
        myCenterTitles =  [ "Downloads", "Firefox Preferences", "Xchat: Network List" ]

-- a trick for fullscreen but stil allow focusing of other WSs
myDoFullFloat :: ManageHook
-- myDoFullFloat = doF W.focusDown <+> doFullFloat
myDoFullFloat = doFullFloat

manageTypes :: ManageHook
manageTypes = checkType --> doCenterFloat

checkType :: Query Bool
checkType = ask >>= \w -> liftX $ do
  m   <- getAtom    "_NET_WM_WINDOW_TYPE_MENU"
  d   <- getAtom    "_NET_WM_WINDOW_TYPE_DIALOG"
  u   <- getAtom    "_NET_WM_WINDOW_TYPE_UTILITY"
  mbr <- getProp32s "_NET_WM_WINDOW_TYPE" w
 
  case mbr of
    Just [r] -> return $ elem (fromIntegral r) [m,d,u]
    _        -> return False

myModMask = mod4Mask

bindKeys = 
    [
      -- bind M-S-; to dmenu
      -- bind M-; to xprops for current window
      -- bind M-Print to take a snapshot
      -- bind M-p to previous window
      -- bind M-n to next window
      -- bind M-g to gridselect
      -- bind M-(S)-(-/=) to resize window a variety of ways -- maybe I'll get aspect ratio preserving later
      ("M-S-;",       spawn "exe=$(dmenu_path | dmenu -i) && eval \"exec $exe\"")
    , ("M-q",         spawn "xmonad --recompile && xmonad --restart")
    , ("M-S-b",       sendMessage ToggleStruts) 
    , ("M-p",         windows W.focusUp)
    , ("M-n",         windows W.focusDown)
    , ("M-S-p",       windows W.swapUp)
    , ("M-S-n",       windows W.swapDown)
    , ("M-g",         goToSelected myGSConfig) 
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
    [ ("M-j")
    , ("M-k")
    ]

myGSConfig = defaultGSConfig

-- Keybinding to toggle the gap for the bar
-- separate from bindKeys
toggleStrutsKey XConfig {XMonad.modMask = modMask} = (modMask, xK_b)

myBar = "xmobar"

myPP = xmobarPP 
    { ppCurrent = xmobarColor "#429942" "" . wrap "<" ">"
    , ppHidden = xmobarColor "#C98F0A" ""
    , ppHiddenNoWindows = xmobarColor "#C9A34E" ""
    , ppUrgent = xmobarColor "#FFFFAF" "" . wrap "[" "]" 
    , ppLayout = xmobarColor "#C9A34E" ""
    , ppTitle =  xmobarColor "#C9A34E" "" . shorten 80
    , ppSep = xmobarColor "#429942" "" " | "
    }

-- how to use this?
myLogHook :: Handle -> X ()
myLogHook h =dynamicLogWithPP $ myPP { ppOutput = hPutStrLn h }

-- will use soon, just not yet
myBorderWidth = 1
colorBG      = "#303030"         -- background
colorFG      = "#606060"         -- foreground
colorFG2     = "#909090"         -- foreground w/ emphasis
colorFG3     = "#c4df90"         -- foreground w/ strong emphasis
colorUrg     = "#cc896d"         -- urgent, peach
colorUrg2    = "#c4df90"         -- urgent, lime

-- will verify these colors some other time
tabTheme1 = defaultTheme 
    { decoHeight = 16
    , activeColor = "#a6c292"
    , activeBorderColor = "#a6c292"
    , activeTextColor = "#000000"
    , inactiveBorderColor = "#000000"
    }

myLayoutHook = avoidStrutsOn [] $ tall ||| wide ||| tab ||| full
    where
        rt      = ResizableTall 1 (2/100) (1/2) []
        tall    = named "[T]=" $ smartBorders rt
        wide    = named "[W]=" $ smartBorders $ Mirror rt
        tab     = named "[+]" $ noBorders $ tabbed shrinkText tabTheme1
        full    = named "[F]" $ noBorders Full

myConfig = gnomeConfig 
    {
      modMask = myModMask
    , focusFollowsMouse = False
    , terminal = "gnome-terminal"
    , manageHook = myManageHook 
               <+> manageHook gnomeConfig
    , layoutHook = myLayoutHook
    , borderWidth = myBorderWidth
    , normalBorderColor = colorBG
    , focusedBorderColor = colorUrg
    } `additionalKeysP` bindKeys `removeKeysP` unbindKeys

-- main = xmonad =<< statusBar myBar myPP toggleStrutsKey myConfig
main = xmonad myConfig

--gathered from:
-- - https://github.com/MrElendig/dotfiles-alice/blob/master/.xmonad/xmonad.hs
-- - http://pastebin.com/m12ffb504
-- - http://pastebin.com/9iWS3hUs
