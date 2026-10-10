/* MapForge tracker: logs bot positions and round events to CSV (docs/TRACKER_SPEC.md).
 *
 * Only bots on T/CT are logged; a round with a human on T/CT gets humans_on_team > 0 and is
 * left out by the analysis. Files: logs/mapforge/<map>_<run_id>/{positions,events,rounds}.csv
 * (relative to cstrike/). After mf_max_rounds finished rounds it writes DONE and quits.
 * Live stream (optional): with mf_live_host set, positions, kills, plants and round results are
 * also sent as small UDP datagrams to the live collector (mapforge.live.collector), which feeds
 * the dashboard's live page. Text format, one message per datagram, fields split by '|':
 *   P|run|map|round|t|tWins|ctWins|live|id,team,alive,x,y,yaw;...   positions (every interval)
 *   K|run|map|round|t|killerTeam|victimTeam|x|y|weapon                kill (victim position)
 *   B|run|map|round|t|site|x|y                                         bomb planted
 *   R|run|map|round|winner|reason|site|tWins|ctWins                    round end
 *   Q|run|map|done                                                     run finished
 * Natives checked against the AMX Mod X 1.10 (git5486) includes.
 */
#include <amxmodx>
#include <csx>
#include <fakemeta>
#include <sockets>

#define TASK_SAMPLE 4711
#define TASK_QUIT 4712
#define TASK_LIVE 4713

new const BOMB_TARGETS[][] = {"func_bomb_target", "info_bomb_target"}

new g_pEnabled, g_pInterval, g_pRunId, g_pMaxRounds
new g_dir[160]
new g_fPos, g_fEv, g_fRnd
new g_runId[64]
new g_round              // round number in this run (counts Round_Start)
new g_done               // finished rounds with a winner
new bool:g_live          // between Round_Start and round end
new bool:g_contact       // first_contact already logged this round
new Float:g_roundStart
new g_humans             // max humans on T/CT seen this round
new g_tStart, g_ctStart
new g_plantSite[8]
new g_pLiveHost, g_pLivePort, g_pLiveInterval
new g_sock, bool:g_sockOk
new g_map[64]
new g_tWins, g_ctWins

public plugin_init()
{
    register_plugin("MapForge Tracker", "1.0", "MapForge")
    g_pEnabled = create_cvar("mf_enabled", "1", _, "Log positions and events")
    g_pInterval = create_cvar("mf_sample_interval", "0.5", _, "Seconds between position samples")
    g_pRunId = create_cvar("mf_run_id", "", _, "Run id (set by the runner)")
    g_pMaxRounds = create_cvar("mf_max_rounds", "0", _, "Quit after N finished rounds (0 = never)")
    g_pLiveHost = create_cvar("mf_live_host", "", _, "Live collector host (empty = no live stream)")
    g_pLivePort = create_cvar("mf_live_port", "27500", _, "Live collector UDP port")
    g_pLiveInterval = create_cvar("mf_live_interval", "0.5", _, "Seconds (game time) between live position updates")

    register_logevent("ev_round_start", 2, "1=Round_Start")
    register_logevent("ev_restart", 2, "1&Restart_Round_")
    register_logevent("ev_restart", 2, "1=Game_Commencing")
    register_event("TextMsg", "ev_textmsg", "a", "2&#")
}

public plugin_cfg()
{
    // the runner's settings (cvars above, game rules); exec'd here so our cvars exist
    server_cmd("exec mapforge.cfg")
    server_exec()
    if (!get_pcvar_num(g_pEnabled))
        return
    new map[64]
    get_mapname(map, charsmax(map))
    get_pcvar_string(g_pRunId, g_runId, charsmax(g_runId))
    if (!g_runId[0])
        formatex(g_runId, charsmax(g_runId), "%d", get_systime())
    mkdir("logs")
    mkdir("logs/mapforge")
    formatex(g_dir, charsmax(g_dir), "logs/mapforge/%s_%s", map, g_runId)
    mkdir(g_dir)
    g_fPos = open_csv("positions.csv", "run_id,round,t,player_id,team,alive,x,y,z,yaw,pitch,hp,weapon")
    g_fEv = open_csv("events.csv", "run_id,round,t,type,actor_id,actor_team,target_id,target_team,ax,ay,az,tx,ty,tz,weapon,extra")
    g_fRnd = open_csv("rounds.csv", "run_id,round,start_time,end_time,winner,reason,plant_site,t_alive_end,ct_alive_end,humans_on_team,t_players,ct_players")
    log_amx("[mapforge] logging to %s", g_dir)
    copy(g_map, charsmax(g_map), map)
    live_open()
}

live_open()
{
    new host[64], err
    get_pcvar_string(g_pLiveHost, host, charsmax(host))
    if (!host[0])
        return
    g_sock = socket_open(host, get_pcvar_num(g_pLivePort), SOCKET_UDP, err)
    if (err != SOCK_ERROR_OK)
    {
        log_amx("[mapforge] live stream off: cannot reach %s (error %d)", host, err)
        return
    }
    g_sockOk = true
    set_task(get_pcvar_float(g_pLiveInterval), "live_tick", TASK_LIVE, _, _, "b")
    log_amx("[mapforge] live stream to %s:%d", host, get_pcvar_num(g_pLivePort))
}

live_send(const msg[])
{
    if (g_sockOk)
        socket_send(g_sock, msg, strlen(msg))
}

public live_tick()
{
    new msg[1400], part[64], team[4], Float:o[3], Float:a[3]
    formatex(msg, charsmax(msg), "P|%s|%s|%d|%.1f|%d|%d|%d|", g_runId, g_map, g_round,
        g_live ? round_time() : 0.0, g_tWins, g_ctWins, g_live)
    for (new id = 1; id <= MaxClients; id++)
    {
        if (!tracked(id))
            continue
        team_name(id, team, charsmax(team))
        pev(id, pev_origin, o)
        pev(id, pev_v_angle, a)
        formatex(part, charsmax(part), "%d,%s,%d,%.0f,%.0f,%.0f;", id, team, is_user_alive(id), o[0], o[1], a[1])
        add(msg, charsmax(msg), part)
    }
    live_send(msg)
}

open_csv(const name[], const header[])
{
    new path[200]
    formatex(path, charsmax(path), "%s/%s", g_dir, name)
    new f = fopen(path, "wt")
    fprintf(f, "%s^n", header)
    return f
}

public plugin_end()
{
    if (g_sockOk)
    {
        new msg[160]
        formatex(msg, charsmax(msg), "Q|%s|%s|done", g_runId, g_map)
        live_send(msg)
        socket_close(g_sock)
        g_sockOk = false
    }
    if (g_fPos) fclose(g_fPos)
    if (g_fEv) fclose(g_fEv)
    if (g_fRnd) fclose(g_fRnd)
}

team_name(id, out[], len)
{
    switch (get_user_team(id))
    {
        case 1: copy(out, len, "T")
        case 2: copy(out, len, "CT")
        default: copy(out, len, "")
    }
}

bool:tracked(id)
{
    if (!is_user_connected(id) || is_user_hltv(id) || !is_user_bot(id))
        return false
    new team = get_user_team(id)
    return team == 1 || team == 2
}

count_humans()
{
    new n
    for (new id = 1; id <= MaxClients; id++)
    {
        if (!is_user_connected(id) || is_user_bot(id) || is_user_hltv(id))
            continue
        new team = get_user_team(id)
        if (team == 1 || team == 2)
            n++
    }
    return n
}

count_alive(team)
{
    new n
    for (new id = 1; id <= MaxClients; id++)
        if (is_user_connected(id) && is_user_alive(id) && get_user_team(id) == team)
            n++
    return n
}

count_team(team)
{
    new n
    for (new id = 1; id <= MaxClients; id++)
        if (is_user_connected(id) && !is_user_hltv(id) && get_user_team(id) == team)
            n++
    return n
}

Float:round_time()
{
    return get_gametime() - g_roundStart
}

public ev_round_start()
{
    if (!get_pcvar_num(g_pEnabled) || !g_fPos)
        return
    g_round++
    g_live = true
    g_contact = false
    g_roundStart = get_gametime()
    g_plantSite[0] = 0
    g_humans = count_humans()
    g_tStart = count_team(1)
    g_ctStart = count_team(2)
    remove_task(TASK_SAMPLE)
    set_task(get_pcvar_float(g_pInterval), "sample", TASK_SAMPLE, _, _, "b")
    sample()
}

public ev_restart()
{
    // restart / game commencing: the running round never counts
    g_live = false
    remove_task(TASK_SAMPLE)
}

public sample()
{
    if (!g_live)
        return
    new h = count_humans()
    if (h > g_humans)
        g_humans = h
    new team[4], weapon[32], Float:o[3], Float:a[3]
    for (new id = 1; id <= MaxClients; id++)
    {
        if (!tracked(id))
            continue
        team_name(id, team, charsmax(team))
        new alive = is_user_alive(id)
        pev(id, pev_origin, o)
        pev(id, pev_v_angle, a)
        weapon[0] = 0
        if (alive)
        {
            new wid = get_user_weapon(id)
            if (wid > 0)
            {
                get_weaponname(wid, weapon, charsmax(weapon))
                replace(weapon, charsmax(weapon), "weapon_", "")
            }
        }
        fprintf(g_fPos, "%s,%d,%.2f,%d,%s,%d,%.1f,%.1f,%.1f,%.1f,%.1f,%d,%s^n",
            g_runId, g_round, round_time(), id, team, alive, o[0], o[1], o[2], a[1], a[0],
            alive ? get_user_health(id) : 0, weapon)
    }
}

// One events.csv row. actor/target 0 = none; extra is a JSON object (already CSV-quoted).
write_event(const type[], actor, target, const weapon[], const extra[])
{
    new at[4], tt[4], Float:ao[3], Float:to[3]
    if (actor > 0 && actor <= MaxClients && is_user_connected(actor))
    {
        team_name(actor, at, charsmax(at))
        pev(actor, pev_origin, ao)
    }
    if (target > 0 && target <= MaxClients && is_user_connected(target))
    {
        team_name(target, tt, charsmax(tt))
        pev(target, pev_origin, to)
    }
    fprintf(g_fEv, "%s,%d,%.2f,%s,%d,%s,%d,%s,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%s,%s^n",
        g_runId, g_round, round_time(), type, actor, at, target > 0 ? target : 0, tt,
        ao[0], ao[1], ao[2], to[0], to[1], to[2], weapon, extra)
}

wpn_name(wpnindex, out[], len)
{
    out[0] = 0
    if (wpnindex > 0)
        xmod_get_wpnname(wpnindex, out, len)
}

public client_damage(attacker, victim, damage, wpnindex, hitplace, TA)
{
    if (!g_live || !tracked(victim))
        return
    new weapon[32], extra[64]
    wpn_name(wpnindex, weapon, charsmax(weapon))
    formatex(extra, charsmax(extra), "^"{^"^"damage^"^":%d,^"^"hitplace^"^":%d}^"", damage, hitplace)
    write_event("damage", attacker, victim, weapon, extra)
    if (!g_contact && attacker != victim && attacker > 0 && attacker <= MaxClients
        && is_user_connected(attacker) && get_user_team(attacker) != get_user_team(victim))
    {
        g_contact = true
        write_event("first_contact", attacker, victim, weapon, "^"{}^"")
    }
}

public client_death(killer, victim, wpnindex, hitplace, TK)
{
    if (!g_live || !tracked(victim))
        return
    new weapon[32], extra[64]
    wpn_name(wpnindex, weapon, charsmax(weapon))
    formatex(extra, charsmax(extra), "^"{^"^"headshot^"^":%d,^"^"teamkill^"^":%d}^"",
        hitplace == HIT_HEAD, TK)
    write_event("kill", killer, victim, weapon, extra)
    if (g_sockOk)
    {
        new msg[200], kt[4], vt[4], Float:o[3]
        if (killer > 0 && killer <= MaxClients && is_user_connected(killer))
            team_name(killer, kt, charsmax(kt))
        team_name(victim, vt, charsmax(vt))
        pev(victim, pev_origin, o)
        formatex(msg, charsmax(msg), "K|%s|%s|%d|%.1f|%s|%s|%.0f|%.0f|%s", g_runId, g_map, g_round,
            round_time(), kt, vt, o[0], o[1], weapon)
        live_send(msg)
    }
}

// Site of a bomb target the planter stands in: letter of a "site_<X>" targetname, else empty
// (the runner then assigns it from the BSP, mapforge.simulate.records).
site_at(id, out[], len)
{
    out[0] = 0
    new Float:o[3], Float:lo[3], Float:hi[3], tn[32]
    pev(id, pev_origin, o)
    for (new c = 0; c < sizeof(BOMB_TARGETS); c++)
    {
        new ent = 0
        while ((ent = engfunc(EngFunc_FindEntityByString, ent, "classname", BOMB_TARGETS[c])) > 0)
        {
            pev(ent, pev_absmin, lo)
            pev(ent, pev_absmax, hi)
            if (c == 1)  // info_bomb_target: point entity, CS uses a radius around it
            {
                pev(ent, pev_origin, lo)
                hi = lo
                for (new k = 0; k < 3; k++) { lo[k] -= 256.0; hi[k] += 256.0; }
            }
            new inside = 1
            for (new k = 0; k < 3; k++)
                if (o[k] < lo[k] - 64.0 || o[k] > hi[k] + 64.0)
                    inside = 0
            if (!inside)
                continue
            pev(ent, pev_targetname, tn, charsmax(tn))
            if (equali(tn, "site_", 5) && tn[5])
            {
                copy(out, len, tn[5])
                strtoupper(out)
            }
            return
        }
    }
}

public bomb_planted(planter)
{
    if (!g_live)
        return
    site_at(planter, g_plantSite, charsmax(g_plantSite))
    new extra[64]
    formatex(extra, charsmax(extra), "^"{^"^"site^"^":^"^"%s^"^"}^"", g_plantSite)
    write_event("bomb_plant", planter, 0, "c4", extra)
    if (g_sockOk)
    {
        new msg[160], Float:o[3]
        pev(planter, pev_origin, o)
        formatex(msg, charsmax(msg), "B|%s|%s|%d|%.1f|%s|%.0f|%.0f", g_runId, g_map, g_round,
            round_time(), g_plantSite, o[0], o[1])
        live_send(msg)
    }
}

public bomb_defused(defuser)
{
    if (g_live)
        write_event("bomb_defuse", defuser, 0, "", "^"{}^"")
}

public bomb_explode(planter, defuser)
{
    if (g_live)
        write_event("bomb_explode", planter, 0, "c4", "^"{}^"")
}

public ev_textmsg()
{
    if (!g_live)
        return
    new msg[32], winner[4], reason[16]
    read_data(2, msg, charsmax(msg))
    if (equal(msg, "#Terrorists_Win")) { copy(winner, 3, "T"); copy(reason, 15, "elimination"); }
    else if (equal(msg, "#CTs_Win")) { copy(winner, 3, "CT"); copy(reason, 15, "elimination"); }
    else if (equal(msg, "#Target_Bombed")) { copy(winner, 3, "T"); copy(reason, 15, "bomb"); }
    else if (equal(msg, "#Bomb_Defused")) { copy(winner, 3, "CT"); copy(reason, 15, "defuse"); }
    else if (equal(msg, "#Target_Saved")) { copy(winner, 3, "CT"); copy(reason, 15, "time"); }
    else if (equal(msg, "#Round_Draw")) { copy(reason, 15, "draw"); }
    else return
    end_round(winner, reason)
}

end_round(const winner[], const reason[])
{
    g_live = false
    remove_task(TASK_SAMPLE)
    new h = count_humans()
    if (h > g_humans)
        g_humans = h
    new extra[96]
    formatex(extra, charsmax(extra), "^"{^"^"winner^"^":^"^"%s^"^",^"^"reason^"^":^"^"%s^"^"}^"",
        winner, reason)
    write_event("round_end", 0, 0, "", extra)
    fprintf(g_fRnd, "%s,%d,%.2f,%.2f,%s,%s,%s,%d,%d,%d,%d,%d^n", g_runId, g_round, g_roundStart,
        get_gametime(), winner, reason, g_plantSite, count_alive(1), count_alive(2), g_humans,
        g_tStart, g_ctStart)
    fflush(g_fPos)
    fflush(g_fEv)
    fflush(g_fRnd)
    if (winner[0])
        g_done++
    if (equal(winner, "T"))
        g_tWins++
    else if (equal(winner, "CT"))
        g_ctWins++
    if (g_sockOk)
    {
        new msg[200]
        formatex(msg, charsmax(msg), "R|%s|%s|%d|%s|%s|%s|%d|%d", g_runId, g_map, g_round, winner,
            reason, g_plantSite, g_tWins, g_ctWins)
        live_send(msg)
    }
    new maxRounds = get_pcvar_num(g_pMaxRounds)
    if (maxRounds > 0 && g_done >= maxRounds)
    {
        new path[200]
        formatex(path, charsmax(path), "%s/DONE", g_dir)
        new f = fopen(path, "wt")
        fprintf(f, "%d^n", g_done)
        fclose(f)
        log_amx("[mapforge] %d rounds done, quitting", g_done)
        set_task(1.0, "quit_server", TASK_QUIT)
    }
}

public quit_server()
{
    plugin_end()
    g_fPos = 0
    g_fEv = 0
    g_fRnd = 0
    server_cmd("quit")
}
