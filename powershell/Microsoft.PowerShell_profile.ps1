Import-Module ZLocation
Import-Module PSReadLine
Set-PSReadlineOption -EditMode Emacs

# http://joonro.github.io/blog/posts/powershell-customizations.html
Set-PSReadLineOption -HistoryNoDuplicates
Set-PSReadLineOption -HistorySearchCursorMovesToEnd
Set-PSReadLineOption -HistorySaveStyle SaveIncrementally
Set-PSReadLineOption -MaximumHistoryCount 100000
Set-PSReadLineOption -BellStyle None


# https://github.com/BurntSushi/ripgrep/blob/master/FAQ.md#how-do-i-create-an-alias-for-ripgrep-on-windows
function rgl {
    $count = @($input).Count
    $input.Reset()

    if ($count) { $input | rg.exe -i -p -M 500 $args }
    else { rg.exe -i $args }
}

function rgf {
    $count = @($input).Count
    $input.Reset()

    if ($count) { $input | rg.exe --files | rg.exe -i -p -M 500 $args }
    else { rg.exe --files | rg.exe -i $args }
}

