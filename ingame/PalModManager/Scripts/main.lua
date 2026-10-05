--[[
  PalModManager -- in-game mod list.

  F8              show / hide
  Up / Down       scroll
  PageUp/PageDown jump a screenful

  Read-only by design. Turning mods on and off happens in the desktop app,
  because UE4SS loads mods once at startup -- a toggle could never apply until
  the next launch anyway, so the natural place to do it is before you start.

  UE4SS mods are discovered live via IterateGameDirectories. That API lists
  directories but NOT files, so pak mods (which are individual .pak files)
  cannot be seen from Lua; those rows come from modlist.txt, which the desktop
  app rewrites every time it runs.
]]

local MOD_NAME = "EZ Pal Mod Manager"
local VERSION  = "1.1.0"

local LIST_FILE = "ue4ss/Mods/PalModManager/modlist.txt"
local PREFIX = "[PalModManager] "

-- Panel geometry in Slate units. Mouse hit-testing reproduces these exact
-- numbers, so a layout change must be made here and nowhere else.
local ORIGIN_X, ORIGIN_Y = 70, 110
local LIST_Y = 34
local ROW_H = 24
local PANEL_W = 470
local VISIBLE = 14

local WHITE   = { R = 1.00, G = 1.00, B = 1.00, A = 1.0 }
local GREEN   = { R = 0.40, G = 0.90, B = 0.45, A = 1.0 }
local GREY    = { R = 0.55, G = 0.55, B = 0.60, A = 1.0 }
local SEL_ON  = { R = 0.65, G = 1.00, B = 0.70, A = 1.0 }
local SEL_OFF = { R = 0.95, G = 0.85, B = 0.55, A = 1.0 }
local DIM     = { R = 0.70, G = 0.70, B = 0.75, A = 1.0 }

local S = { open = false, panel = nil, rows = {}, mods = {}, sel = 1, top = 1 }

local function log(msg) print(PREFIX .. tostring(msg) .. "\n") end

local function try(fn, ...)
    local ok, res = pcall(fn, ...)
    if ok then return res end
    return nil
end

local function alive(o)
    return o ~= nil and try(function() return o:IsValid() end) == true
end

-- ---------------------------------------------------------------- data

-- Paths relative to the game's working directory (…/Pal/Binaries/Win64), so the
-- mod is portable and needs no configuration when shipped.
local MODS_DIR  = "ue4ss/Mods"
local PAK_DIRS  = { "../../Content/Paks/~mods", "../../Content/Paks/LogicMods" }

local BUILTIN = {
    BPModLoaderMod = true, BPML_GenericFunctions = true, CheatManagerEnablerMod = true,
    ConsoleCommandsMod = true, ConsoleEnablerMod = true, Keybinds = true,
    LineTraceMod = true, SplitScreenMod = true, ActorDumperMod = true,
    jsbLuaProfilerMod = true, shared = true, PalModManager = true,
}

-- IterateGameDirectories() returns nested tables keyed directly by entry name
-- -- confirmed on the experimental build, whose root keys are the Palworld
-- folder's own subdirectories. "Game" is UE4SS's alias for the Pal/ folder.
-- Metadata keys are prefixed with __ and are skipped.
local function entries(node)
    local out = {}
    if node == nil then return out end
    local ok = pcall(function()
        for k, v in pairs(node) do
            local name = tostring(k)
            if name:sub(1, 2) ~= "__" then out[#out + 1] = { name = name, node = v } end
        end
    end)
    if not ok then return {} end
    return out
end

local function logKeys(label, node)
    local names = {}
    for _, e in ipairs(entries(node)) do names[#names + 1] = e.name end
    log(label .. ": " .. (#names > 0 and table.concat(names, ", ") or "<empty>"))
end

local function descend(node, parts)
    for _, want in ipairs(parts) do
        if node == nil then return nil end
        local nxt = try(function() return node[want] end)
        if nxt == nil then                      -- tolerate case differences
            for _, e in ipairs(entries(node)) do
                if e.name:lower() == want:lower() then nxt = e.node; break end
            end
        end
        node = nxt
    end
    return node
end

-- Returns a list of entry names under the given path, or nil if unavailable.
-- Files and directories are not distinguished: callers filter by name, which
-- avoids depending on any per-node metadata.
local function listDir(parts)
    local root = try(IterateGameDirectories)
    if root == nil then return nil end
    local node = descend(root, parts)
    if node == nil then return nil end
    local out = {}
    for _, e in ipairs(entries(node)) do out[#out + 1] = e.name end
    return out
end

local function fileExists(p)
    local h = io.open(p, "r")
    if h then h:close(); return true end
    return false
end

-- Primary path: discover mods directly, so no external script is needed.
local function scanMods()
    local mods = {}
    -- Experimental layout first, then the flat layout used by stable 3.0.1.
    local names = listDir({ "Game", "Binaries", "Win64", "ue4ss", "Mods" })
    if names == nil or #names == 0 then
        names = listDir({ "Game", "Binaries", "Win64", "Mods" })
        if names and #names > 0 then MODS_DIR = "Mods" end
    end
    if names == nil or #names == 0 then
        logKeys("scan failed; root contained", try(IterateGameDirectories))
        return nil
    end
    table.sort(names)
    for _, n in ipairs(names) do
        -- Only real mod folders have one of these; skips stray files and
        -- anything the directory API reports that is not a mod.
        local path = MODS_DIR .. "/" .. n
        local isMod = fileExists(path .. "/enabled.txt")
            or fileExists(path .. "/enabled.txt.disabled")
            or fileExists(path .. "/Scripts/main.lua")
            or fileExists(path .. "/dlls/main.dll")
        if isMod and not BUILTIN[n] then
            local kind = fileExists(path .. "/dlls/main.dll") and "c++" or "lua"
            mods[#mods + 1] = {
                name = n, kind = kind, path = path,
                on = fileExists(path .. "/enabled.txt"),
            }
        end
    end
    local pakFound = 0
    for i, rel in ipairs(PAK_DIRS) do
        local sub = (i == 1) and "~mods" or "LogicMods"
        local files = listDir({ "Game", "Content", "Paks", sub })
        if files == nil or #files == 0 then
            -- Narrow down which level the directory API stops at.
            local root = try(IterateGameDirectories)
            logKeys("  Paks probe: Game", descend(root, { "Game" }))
            logKeys("  Paks probe: Game/Content", descend(root, { "Game", "Content" }))
            logKeys("  Paks probe: Game/Content/Paks",
                    descend(root, { "Game", "Content", "Paks" }))
        end
        pakFound = pakFound + #(files or {})
        for _, fn in ipairs(files or {}) do
            local base = fn:match("^(.-)%.pak%.disabled$")
            local on = base == nil
            base = base or fn:match("^(.-)%.pak$")
            if base then
                mods[#mods + 1] = {
                    name = base, kind = "pak", on = on,
                    path = rel .. "/" .. base .. ".pak",
                }
            end
        end
    end
    return mods, pakFound
end

-- Fallback: the file palmods.py writes, for builds where the directory API
-- differs from every shape handled above.
local function readListFile()
    local mods = {}
    local f = io.open(LIST_FILE, "r")
    if not f then return mods end
    for line in f:lines() do
        if line ~= "" and line:sub(1, 1) ~= "#" then
            local name, kind, on, path = line:match("^([^|]*)|([^|]*)|([^|]*)|(.*)$")
            if name then
                mods[#mods + 1] = { name = name, kind = kind, on = (on == "1"), path = path }
            end
        end
    end
    f:close()
    return mods
end

local function summarise(mods, source)
    local n = { lua = 0, ["c++"] = 0, pak = 0 }
    local names = {}
    for _, m in ipairs(mods) do
        n[m.kind] = (n[m.kind] or 0) + 1
        names[#names + 1] = m.name .. (m.on and "" or "(off)")
    end
    log(string.format("scan via %s: %d mods (%d lua, %d c++, %d pak) -- %s",
        source, #mods, n.lua, n["c++"], n.pak, table.concat(names, ", ")))
end

local function readList()
    local scanned, pakCount = scanMods()
    if scanned and #scanned > 0 then
        -- UE4SS mods scanned fine but the Paks tree did not enumerate; fill the
        -- gap from modlist.txt so the list is still complete.
        if (pakCount or 0) == 0 then
            local merged = 0
            for _, m in ipairs(readListFile()) do
                if m.kind == "pak" then
                    scanned[#scanned + 1] = m
                    merged = merged + 1
                end
            end
            if merged > 0 then
                log("pak directory scan empty -- merged " .. merged ..
                    " pak entries from modlist.txt")
            end
        end
        summarise(scanned, (pakCount or 0) > 0 and "live directory scan"
                            or "live scan + modlist.txt paks")
        return scanned
    end
    log("directory scan unavailable -- falling back to modlist.txt")
    local fromFile = readListFile()
    if #fromFile == 0 then
        log("no mods found; run: python palmods.py status")
    else
        summarise(fromFile, "modlist.txt")
    end
    return fromFile
end

-- ---------------------------------------------------------------- ui

local function make(classPath, outer)
    local c = try(StaticFindObject, classPath)
    if c == nil then return nil end
    return try(StaticConstructObject, c, outer)
end

local function findCanvas(tree)
    local root = try(function() return tree.RootWidget end)
    if not alive(root) then return nil end
    local function isCanvas(w)
        return try(function() return w:GetClass():GetFName():ToString() end) == "CanvasPanel"
    end
    if isCanvas(root) then return root end
    local n = try(function() return root:GetChildrenCount() end) or 0
    for i = 0, n - 1 do
        local c = try(function() return root:GetChildAt(i) end)
        if alive(c) and isCanvas(c) then return c end
    end
    return root
end

local function text(tree, str, size, colour)
    local t = make("/Script/UMG.TextBlock", tree)
    if t == nil then return nil end
    try(function() t:SetText(FText(str)) end)
    try(function() t.Font.Size = (size or 15) + 0.0 end)
    if colour then
        try(function() t:SetColorAndOpacity({ SpecifiedColor = colour, ColorUseRule = 0 }) end)
    end
    return t
end

local function visibleCount() return math.min(VISIBLE, #S.mods) end

local function clampScroll()
    if S.sel < 1 then S.sel = #S.mods end
    if S.sel > #S.mods then S.sel = 1 end
    if S.sel < S.top then S.top = S.sel end
    if S.sel > S.top + VISIBLE - 1 then S.top = S.sel - VISIBLE + 1 end
    local maxTop = math.max(1, #S.mods - VISIBLE + 1)
    if S.top > maxTop then S.top = maxTop end
    if S.top < 1 then S.top = 1 end
end

local function rowLabel(idx)
    local m = S.mods[idx]
    if not m then return "" end
    return string.format("%s %-24s %-5s %s",
        " ", m.name:sub(1, 24), m.kind, m.on and "ON" or "off")
end

local function rowColour(idx)
    local m = S.mods[idx]
    if not m then return GREY end
    return m.on and GREEN or GREY
end

-- Repaint the fixed set of row widgets against the current scroll window.
local function repaint()
    for slot = 1, visibleCount() do
        local idx = S.top + slot - 1
        local t = S.rows[slot]
        if alive(t) then
            try(function() t:SetText(FText(rowLabel(idx))) end)
            try(function()
                t:SetColorAndOpacity({ SpecifiedColor = rowColour(idx), ColorUseRule = 0 })
            end)
        end
    end
    if alive(S.footer) then
        local more = #S.mods > VISIBLE
            and string.format("  [%d-%d of %d]", S.top,
                              math.min(S.top + VISIBLE - 1, #S.mods), #S.mods)
            or ""
        try(function()
            S.footer:SetText(FText(
                "F8 close   Up/Down scroll   (toggle mods in the desktop app)" .. more))
        end)
    end
end

local function destroy()
    if alive(S.panel) then try(function() S.panel:RemoveFromParent() end) end
    S.panel, S.rows, S.footer = nil, {}, nil
    S.open = false
end

local function build()
    local host = try(FindFirstOf, "WBP_PalOverallUILayout_C")
    if not alive(host) then log("no UI layout widget found"); return false end
    local tree = try(function() return host.WidgetTree end)
    if not alive(tree) then log("host has no WidgetTree"); return false end
    local canvas = findCanvas(tree)
    if not alive(canvas) then log("no canvas to attach to"); return false end

    local panel = make("/Script/UMG.CanvasPanel", tree)
    if panel == nil then log("could not create panel"); return false end
    local rows = visibleCount()
    local panelH = LIST_Y + rows * ROW_H + 42

    local pslot = try(function() return canvas:AddChildToCanvas(panel) end)
    if pslot then
        try(function() pslot:SetAutoSize(false) end)
        try(function() pslot:SetAlignment({ X = 0.0, Y = 0.0 }) end)
        try(function() pslot:SetPosition({ X = ORIGIN_X + 0.0, Y = ORIGIN_Y + 0.0 }) end)
        try(function() pslot:SetSize({ X = PANEL_W + 0.0, Y = panelH + 0.0 }) end)
    end
    S.panel = panel

    local function put(w, x, y)
        if w == nil then return end
        local s = try(function() return panel:AddChildToCanvas(w) end)
        if s then
            try(function() s:SetAutoSize(true) end)
            try(function() s:SetPosition({ X = x + 0.0, Y = y + 0.0 }) end)
        end
    end

    -- Backdrop first: a CanvasPanel paints in insertion order, so this must
    -- exist before any text or it covers the list. Without it the panel is
    -- unreadable against the bright main-menu art.
    local back = make("/Script/UMG.Border", tree)
    if back ~= nil then
        try(function() back:SetBrushColor({ R = 0.04, G = 0.05, B = 0.08, A = 0.85 }) end)
        local bs = try(function() return panel:AddChildToCanvas(back) end)
        if bs then
            try(function() bs:SetAutoSize(false) end)
            try(function() bs:SetAlignment({ X = 0.0, Y = 0.0 }) end)
            try(function() bs:SetPosition({ X = -14.0, Y = -12.0 }) end)
            try(function() bs:SetSize({ X = PANEL_W + 0.0, Y = panelH + 0.0 }) end)
        end
    end

    put(text(tree, MOD_NAME:upper() .. "   v" .. VERSION, 18, WHITE), 0, 0)
    for slot = 1, rows do
        local t = text(tree, "", 15, GREY)
        S.rows[slot] = t
        put(t, 0, LIST_Y + (slot - 1) * ROW_H)
    end
    S.footer = text(tree, "", 13, DIM)
    put(S.footer, 0, LIST_Y + rows * ROW_H + 10)

    repaint()
    return true
end

local function toggle()
    if S.open then destroy(); return end
    S.mods = readList()
    if #S.mods == 0 then return end
    if S.sel > #S.mods then S.sel = 1 end
    clampScroll()
    if build() then S.open = true else destroy() end
end

local function move(delta)
    if not S.open or #S.mods == 0 then return end
    S.top = S.top + delta
    local maxTop = math.max(1, #S.mods - VISIBLE + 1)
    if S.top > maxTop then S.top = maxTop end
    if S.top < 1 then S.top = 1 end
    repaint()
end

-- ---------------------------------------------------------------- keys

local function bind(key, fn)
    if key == nil then return end
    pcall(RegisterKeyBind, key, function()
        ExecuteInGameThread(function()
            local ok, err = pcall(fn)
            if not ok then log("error: " .. tostring(err)) end
        end)
    end)
end

bind(Key.F8, toggle)
bind(Key.UP_ARROW, function() move(-1) end)
bind(Key.DOWN_ARROW, function() move(1) end)
bind(Key.PAGE_UP, function() move(-VISIBLE) end)
bind(Key.PAGE_DOWN, function() move(VISIBLE) end)
-- Key naming varies between UE4SS builds; bind() ignores nils, so cover both.

log(MOD_NAME .. " " .. VERSION .. " loaded -- press F8")
