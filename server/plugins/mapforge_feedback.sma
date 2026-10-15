/* MapForge Feedback: a human walks the map on a feedback server and leaves notes where they
 * stand and look. Each note records the player's eye, the point they aim at (a trace from the
 * eye) and the text; mapforge.feedback collects them into the map's wishes.
 *
 * Ways in (all end up the same):
 *   say !fb <text>   or  say /fb <text>        a note about what you look at
 *   bind f "messagemode mf_fb"                  a key: press, type, Enter
 *   say !fbm                                    a menu: pick a category, then type
 *
 * File: logs/mapforge/feedback_<map>.jsonl (relative to cstrike/), one JSON object per line.
 * Harmless on simulation servers: it only answers these commands.
 */

#include <amxmodx>
#include <amxmisc>

#define MAX_TEXT 190

new const CATEGORIES[][] = {"layout", "texture", "light", "gameplay", "bug", "good"}
new g_category[33]          // index into CATEGORIES, -1 = none (per player)
new g_count
new g_pNoBots

public plugin_init()
{
    register_plugin("MapForge Feedback", "1.0", "MapForge")
    register_clcmd("say", "cmd_say")
    register_clcmd("say_team", "cmd_say")
    register_clcmd("mf_fb", "cmd_fb")       // messagemode mf_fb
    g_pNoBots = create_cvar("mf_feedback_nobots", "0", _, "Kick every bot that joins (a feedback server is for humans)")
    mkdir("logs/mapforge")
}

public client_putinserver(id)
{
    g_category[id] = -1
    if (is_user_bot(id)) {
        if (get_pcvar_num(g_pNoBots)) set_task(0.5, "task_kick", get_user_userid(id))
        return
    }
    set_task(5.0, "task_hello", id)
}

public task_kick(userid)
{
    server_cmd("kick #%d ^"feedback server: no bots^"", userid)
}

public task_hello(id)
{
    if (!is_user_connected(id)) return
    client_print(id, print_chat, "[MapForge] Feedback: say !fb <text> about what you look at, or !fbm for a menu.")
    client_print(id, print_chat, "[MapForge] Tip: bind a key: bind f ^"messagemode mf_fb^"  (sv_cheats 1: noclip to fly)")
}

public cmd_say(id)
{
    new text[MAX_TEXT + 8]
    read_args(text, charsmax(text))
    remove_quotes(text)
    trim(text)
    if (equali(text, "!fbm") || equali(text, "/fbm")) {
        show_menu_categories(id)
        return PLUGIN_HANDLED
    }
    if (equal(text, "!fb ", 4) || equal(text, "/fb ", 4)) {
        new note[MAX_TEXT]
        copy(note, charsmax(note), text[4])
        trim(note)
        if (note[0]) record(id, note)
        return PLUGIN_HANDLED
    }
    return PLUGIN_CONTINUE
}

public cmd_fb(id)
{
    new note[MAX_TEXT]
    read_args(note, charsmax(note))
    remove_quotes(note)
    trim(note)
    if (note[0]) record(id, note)
    return PLUGIN_HANDLED
}

show_menu_categories(id)
{
    new menu = menu_create("MapForge feedback: what kind?", "menu_handler")
    for (new i = 0; i < sizeof CATEGORIES; i++) menu_additem(menu, CATEGORIES[i])
    menu_display(id, menu)
}

public menu_handler(id, menu, item)
{
    menu_destroy(menu)
    if (item < 0) return PLUGIN_HANDLED
    g_category[id] = item
    client_print(id, print_chat, "[MapForge] %s: type your note and press Enter.", CATEGORIES[item])
    client_cmd(id, "messagemode mf_fb")
    return PLUGIN_HANDLED
}

json_escape(const src[], dst[], len)
{
    new j = 0
    for (new i = 0; src[i] && j < len - 2; i++) {
        if (src[i] == '"' || src[i] == '\') dst[j++] = '\'
        if (src[i] < 32) continue
        dst[j++] = src[i]
    }
    dst[j] = 0
}

record(id, const note[])
{
    new eye[3], aim[3], foot[3], map[32], name[32], stamp[24], path[96]
    get_user_origin(id, eye, 1)   // eyes
    get_user_origin(id, aim, 3)   // where the crosshair hits
    get_user_origin(id, foot, 0)
    get_mapname(map, charsmax(map))
    get_user_name(id, name, charsmax(name))
    get_time("%Y-%m-%d %H:%M:%S", stamp, charsmax(stamp))
    new esc_note[MAX_TEXT * 2], esc_name[64]
    json_escape(note, esc_note, charsmax(esc_note))
    json_escape(name, esc_name, charsmax(esc_name))
    new cat[16]
    if (g_category[id] >= 0) copy(cat, charsmax(cat), CATEGORIES[g_category[id]])
    g_category[id] = -1

    formatex(path, charsmax(path), "logs/mapforge/feedback_%s.jsonl", map)
    new f = fopen(path, "at")
    if (!f) {
        client_print(id, print_chat, "[MapForge] could not write %s", path)
        return
    }
    fprintf(f, "{^"time^": ^"%s^", ^"map^": ^"%s^", ^"player^": ^"%s^", ^"category^": ^"%s^", ^"text^": ^"%s^", ^"eye^": [%d, %d, %d], ^"aim^": [%d, %d, %d], ^"origin^": [%d, %d, %d]}^n",
        stamp, map, esc_name, cat, esc_note, eye[0], eye[1], eye[2], aim[0], aim[1], aim[2], foot[0], foot[1], foot[2])
    fclose(f)
    g_count++
    client_print(id, print_chat, "[MapForge] feedback #%d saved (aim %d %d %d)", g_count, aim[0], aim[1], aim[2])
}
