--[[
  PalModManagerProbe -- stage 2, step 1.

  Read-only. Dumps the live widget tree of Palworld's native Mod Management tab
  so the injection code can target real child names instead of guesses.

  Open Settings -> Mod Management in game, then press F9.
  Output lands in ue4ss/UE4SS.log, prefixed [PMMProbe].

  Nothing here modifies the game. Delete the folder when the dump is captured.
]]

local PREFIX = "[PMMProbe] "
local MAX_DEPTH = 12

local function log(fmt, ...)
    local ok, msg = pcall(string.format, fmt, ...)
    print(PREFIX .. (ok and msg or tostring(fmt)) .. "\n")
end

-- Every reflected call can fail on a stale or half-built object; never let the
-- probe take the game down with it.
local function try(fn, ...)
    local ok, res = pcall(fn, ...)
    if ok then return res end
    return nil
end

local function alive(o)
    if not o then return false end
    return try(function() return o:IsValid() end) == true
end

local function className(o)
    return try(function() return o:GetClass():GetFName():ToString() end) or "?"
end

local function objName(o)
    return try(function() return o:GetFName():ToString() end) or "?"
end

-- UPanelWidget exposes GetChildrenCount/GetChildAt; leaf widgets do not.
local function children(w)
    local n = try(function() return w:GetChildrenCount() end)
    if not n or n == 0 then return {} end
    local out = {}
    for i = 0, n - 1 do
        local c = try(function() return w:GetChildAt(i) end)
        if alive(c) then out[#out + 1] = c end
    end
    return out
end

-- A nested UUserWidget owns its own WidgetTree; without descending into it the
-- walk stops at the first user widget it meets.
local function innerRoot(w)
    local tree = try(function() return w.WidgetTree end)
    if not alive(tree) then return nil end
    local r = try(function() return tree.RootWidget end)
    return alive(r) and r or nil
end

local function walk(w, depth, seen)
    if not alive(w) or depth > MAX_DEPTH then return end
    local key = try(function() return w:GetFullName() end)
    if key then
        if seen[key] then return end
        seen[key] = true
    end

    local kids = children(w)
    local inner = innerRoot(w)
    local text = try(function() return w:GetText():ToString() end)
    local items = try(function() return w:GetNumItems() end)     -- UListView & friends

    log("%s%s : %s%s%s%s%s",
        string.rep("  ", depth),
        objName(w), className(w),
        #kids > 0 and ("  panel(" .. #kids .. ")") or "",
        inner and "  [userwidget]" or "",
        items and ("  items=" .. tostring(items)) or "",
        (text and text ~= "") and ("  text=\"" .. text .. "\"") or "")

    for _, c in ipairs(kids) do walk(c, depth + 1, seen) end
    if inner then walk(inner, depth + 1, seen) end
end

-- Objects living under /Game/ are asset templates; real on-screen widgets are
-- transient. Prefer the latter.
local function liveInstances(shortName)
    local all = try(FindAllOf, shortName)
    local live, template = {}, nil
    if type(all) == "table" then
        for _, o in ipairs(all) do
            if alive(o) then
                local fn = try(function() return o:GetFullName() end) or ""
                if fn:find("Transient", 1, true) then live[#live + 1] = o
                else template = template or o end
            end
        end
    end
    return live, template
end

local function dumpWidget(shortName)
    local live, template = liveInstances(shortName)
    if #live == 0 then
        if template then
            log("%s -- only an asset template is loaded, no live instance", shortName)
        else
            log("%s -- not found", shortName)
        end
        return false
    end
    for _, root in ipairs(live) do
        log("=== %s (live) ===", shortName)
        log("  full name: %s", try(function() return root:GetFullName() end) or "?")
        local start = innerRoot(root)
        log("  -- widget tree --")
        walk(start or root, 1, {})
    end
    return true
end

local function probe()
    log("---------- probe start ----------")
    local found = false
    -- WBP_ModList_ForDisplay_C is the one confirmed live on screen; the others
    -- may only ever exist as templates inside it.
    for _, name in ipairs({
        "WBP_ModList_ForDisplay_C",
        "WBP_Option_ModMenu_C",
        "WBP_Option_ModMenu_ModList_C",
    }) do
        found = dumpWidget(name) or found
    end

    -- Fallback: sweep every loaded UObject whose class mentions Mod, so we still
    -- learn the real class names even if the guesses above are all wrong.
    if not found then
        log("no target widgets live; sweeping loaded objects for 'Mod' classes")
        local hits, seen = 0, {}
        try(ForEachUObject, function(obj)
            if hits > 60 then return end
            local cn = className(obj)
            if cn:find("Mod") and not cn:find("Mode") and not cn:find("Model") then
                if not seen[cn] then
                    seen[cn] = true
                    hits = hits + 1
                    log("  class: %s   (example: %s)", cn, objName(obj))
                end
            end
        end)
        if hits == 0 then log("  nothing found -- open the Mod Management tab first") end
    end
    log("---------- probe end ----------")
end

RegisterKeyBind(Key.F9, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(probe)
        if not ok then log("probe error: %s", tostring(err)) end
    end)
end)

log("loaded -- open Settings > Mod Management, then press F9")
