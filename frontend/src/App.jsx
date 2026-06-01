import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock3,
  KeyRound,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react'
import './App.css'

const FALLBACK_SLOTS = [
  { index: 0, label: '1', start: '08:00', end: '08:45' },
  { index: 1, label: '2', start: '08:50', end: '09:35' },
  { index: 2, label: '3', start: '09:50', end: '10:35' },
  { index: 3, label: '4', start: '10:40', end: '11:25' },
  { index: 4, label: '5', start: '11:30', end: '12:15' },
  { index: 5, label: '6', start: '13:00', end: '13:45' },
  { index: 6, label: '7', start: '13:50', end: '14:35' },
  { index: 7, label: '8', start: '14:45', end: '15:30' },
  { index: 8, label: '9', start: '15:40', end: '16:25' },
  { index: 9, label: '10', start: '16:35', end: '17:20' },
  { index: 10, label: '11', start: '17:25', end: '18:10' },
  { index: 11, label: '12', start: '18:30', end: '19:15' },
  { index: 12, label: '13', start: '19:20', end: '20:05' },
  { index: 13, label: '14', start: '20:10', end: '20:55' },
]

function localDateString(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function requestBody(credentials, extras = {}) {
  return {
    account: credentials.account.trim() || null,
    password: credentials.password || null,
    ...extras,
  }
}

function normalizeCampusId(campusId) {
  const value = String(campusId || '01').trim()
  if (/^\d+$/.test(value)) return value.padStart(2, '0')
  return value
}

function normalizeClassroomsCache(data) {
  if (!data) return null
  if (Array.isArray(data.campuses)) return data
  if (Array.isArray(data.rooms)) {
    return {
      cache_version: data.cache_version || 0,
      target_date: data.target_date || localDateString(),
      fetched_at: data.fetched_at || '',
      realtime: data.realtime ?? true,
      provider: data.provider || 'sjd',
      campuses: [data],
    }
  }
  return null
}

function getCampusClassrooms(cache, campusId) {
  const normalizedCampusId = normalizeCampusId(campusId)
  return (cache?.campuses || []).find((campus) => normalizeCampusId(campus.campus_id) === normalizedCampusId) || null
}

function mergeCampusClassrooms(cache, campusClassrooms) {
  const current = normalizeClassroomsCache(cache) || {
    cache_version: 0,
    target_date: campusClassrooms.target_date || localDateString(),
    fetched_at: campusClassrooms.fetched_at || '',
    realtime: campusClassrooms.realtime ?? true,
    provider: campusClassrooms.provider || 'sjd',
    campuses: [],
  }
  const normalizedCampusId = normalizeCampusId(campusClassrooms.campus_id)
  return {
    ...current,
    target_date: campusClassrooms.target_date || current.target_date,
    fetched_at: campusClassrooms.fetched_at || current.fetched_at,
    campuses: [
      ...current.campuses.filter((campus) => normalizeCampusId(campus.campus_id) !== normalizedCampusId),
      campusClassrooms,
    ],
  }
}

async function apiPost(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail || `请求失败: HTTP ${response.status}`)
  }
  return response.json()
}

function getWeekState(courses, termStartDate, targetDate) {
  if (!termStartDate || !targetDate) {
    return { weekNumber: 0, weekday: 0, busySlots: [], dayCourses: [] }
  }
  const start = new Date(`${termStartDate}T00:00:00`)
  const target = new Date(`${targetDate}T00:00:00`)
  const days = Math.floor((target - start) / 86400000)
  const weekNumber = Math.floor(days / 7) + 1
  const weekday = target.getDay() === 0 ? 7 : target.getDay()
  const dayCourses = courses
    .filter((course) => course.weekday === weekday && course.week_numbers.includes(weekNumber))
    .sort((a, b) => a.start_slot - b.start_slot || a.name.localeCompare(b.name))
  const busySlots = [...new Set(dayCourses.flatMap((course) => {
    const slots = []
    for (let slot = course.start_slot; slot <= course.end_slot; slot += 1) slots.push(slot)
    return slots
  }))].sort((a, b) => a - b)
  return { weekNumber, weekday, busySlots, dayCourses }
}

function slotsToRanges(slots, slotMeta) {
  if (!slots.length) return []
  const sorted = [...new Set(slots)].sort((a, b) => a - b)
  const ranges = []
  let start = sorted[0]
  let prev = sorted[0]
  for (const slot of sorted.slice(1)) {
    if (slot === prev + 1) {
      prev = slot
    } else {
      ranges.push({ start, end: prev, label: `${slotMeta[start].start}-${slotMeta[prev].end}` })
      start = slot
      prev = slot
    }
  }
  ranges.push({ start, end: prev, label: `${slotMeta[start].start}-${slotMeta[prev].end}` })
  return ranges
}

function displayBuildingName(name) {
  return String(name || '').replaceAll('未来学习大楼', '主楼')
}

function roomCoversSlots(room, slots) {
  if (!slots.length) return false
  const availableSlots = new Set(room.available_slots || [])
  return slots.every((slot) => availableSlots.has(slot))
}

function App() {
  const [metadata, setMetadata] = useState({ campuses: [], slots: FALLBACK_SLOTS })
  const [credentials, setCredentials] = useState({ account: '', password: '' })
  const [termId, setTermId] = useState('2025-2026-2')
  const [termStartDate, setTermStartDate] = useState('2026-03-02')
  const [campusId, setCampusId] = useState('01')
  const [schedule, setSchedule] = useState(null)
  const [classroomsCache, setClassroomsCache] = useState(null)
  const [recommendations, setRecommendations] = useState(null)
  const [selectedSlots, setSelectedSlots] = useState([])
  const [selectedBuildings, setSelectedBuildings] = useState([])
  const [minSeats, setMinSeats] = useState(0)
  const [usePersonalSchedule, setUsePersonalSchedule] = useState(true)
  const [showRecommendationHighlight, setShowRecommendationHighlight] = useState(true)
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/metadata')
      .then((response) => response.json())
      .then((data) => {
        setMetadata(data)
        setTermId(data.default_term_id)
        setTermStartDate(data.default_term_start_date)
        setCampusId(data.campuses[0]?.id || '01')
      })
      .catch(() => {
        setMetadata({ campuses: [{ id: '01', name: '西土城' }], slots: FALLBACK_SLOTS })
      })
  }, [])

  const slotMeta = metadata.slots?.length ? metadata.slots : FALLBACK_SLOTS
  const todayDate = localDateString()
  const courses = useMemo(() => (schedule ? schedule.courses : []), [schedule])
  const weekState = useMemo(
    () => getWeekState(courses, schedule?.term_start_date || termStartDate, todayDate),
    [courses, schedule?.term_start_date, todayDate, termStartDate],
  )
  const busySlots = useMemo(
    () => (usePersonalSchedule ? weekState.busySlots : []),
    [usePersonalSchedule, weekState.busySlots],
  )
  const freeSlots = useMemo(
    () => slotMeta.map((slot) => slot.index).filter((slot) => !busySlots.includes(slot)),
    [busySlots, slotMeta],
  )
  const classrooms = useMemo(
    () => getCampusClassrooms(classroomsCache, campusId),
    [classroomsCache, campusId],
  )
  const buildings = useMemo(() => {
    const names = [...new Set((classrooms?.rooms || []).map((room) => room.building))]
    return names.sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  }, [classrooms])
  const filteredRooms = useMemo(() => {
    return (classrooms?.rooms || [])
      .filter((room) => !selectedBuildings.length || selectedBuildings.includes(room.building))
      .filter((room) => !room.size || room.size >= minSeats)
      .filter((room) => roomCoversSlots(room, selectedSlots))
      .sort((a, b) => a.building.localeCompare(b.building, 'zh-Hans-CN') || a.room.localeCompare(b.room, 'zh-Hans-CN'))
  }, [classrooms, minSeats, selectedBuildings, selectedSlots])

  function updateCredential(field, value) {
    setCredentials((current) => ({ ...current, [field]: value }))
  }

  function toggleSlot(slotIndex) {
    setRecommendations(null)
    setSelectedSlots((current) => (
      current.includes(slotIndex)
        ? current.filter((slot) => slot !== slotIndex)
        : [...current, slotIndex].sort((a, b) => a - b)
    ))
  }

  function toggleBuilding(building) {
    setRecommendations(null)
    setSelectedBuildings((current) => (
      current.includes(building)
        ? current.filter((item) => item !== building)
        : [...current, building]
    ))
  }

  function selectCampus(nextCampusId) {
    setCampusId(nextCampusId)
    setSelectedBuildings([])
    setRecommendations(null)
  }

  function togglePersonalSchedule() {
    const nextValue = !usePersonalSchedule
    setUsePersonalSchedule(nextValue)
    setRecommendations(null)
    if (nextValue) {
      setSelectedSlots((current) => current.filter((slot) => !weekState.busySlots.includes(slot)))
    } else {
      setSelectedSlots((current) => (
        [...new Set([...current, ...weekState.busySlots])].sort((a, b) => a - b)
      ))
    }
  }

  async function runTask(name, task) {
    setLoading(name)
    setError('')
    try {
      await task()
    } catch (taskError) {
      setError(taskError.message)
    } finally {
      setLoading('')
    }
  }

  async function loadSchedule() {
    await runTask('schedule', async () => {
      const data = await apiPost('/api/schedule', requestBody(credentials, {
        term_id: termId,
        term_start_date: termStartDate,
      }))
      setSchedule(data)
      setUsePersonalSchedule(true)
      const nextState = getWeekState(data.courses, data.term_start_date, todayDate)
      const nextFreeSlots = slotMeta.map((slot) => slot.index).filter((slot) => !nextState.busySlots.includes(slot))
      setSelectedSlots(nextFreeSlots)
      setRecommendations(null)
    })
  }

  async function loadClassrooms() {
    await runTask('classrooms', async () => {
      const data = await apiPost('/api/classrooms/all', requestBody(credentials, {
        target_date: todayDate,
      }))
      setClassroomsCache(normalizeClassroomsCache(data))
      setRecommendations(null)
    })
  }

  async function runRecommendations() {
    await runTask('recommendations', async () => {
      const data = await apiPost('/api/recommendations', requestBody(credentials, {
        campus_id: campusId,
        target_date: todayDate,
        term_id: termId,
        term_start_date: termStartDate,
        selected_slots: selectedSlots,
        buildings: selectedBuildings,
        min_seats: Number(minSeats) || 0,
        use_schedule_filter: usePersonalSchedule,
      }))
      setClassroomsCache((current) => mergeCampusClassrooms(current, data.classrooms))
      if (!schedule) {
        setSchedule({
          term_id: termId,
          term_start_date: termStartDate,
          fetched_at: data.classrooms.fetched_at,
          courses: data.schedule.courses,
        })
      }
      setRecommendations(data)
      setShowRecommendationHighlight(true)
      setSelectedSlots(data.selected_slots)
    })
  }

  const selectedRanges = slotsToRanges(selectedSlots, slotMeta)
  const recommendationItems = useMemo(
    () => (recommendations ? recommendations.recommendations : []),
    [recommendations],
  )
  const recommendationByRoom = useMemo(
    () => new Map(
      recommendationItems
        .filter((item) => selectedSlots.length > 0 && roomCoversSlots(
          { available_slots: item.matched_slots },
          selectedSlots,
        ))
        .map((item) => [item.classroom.id, item]),
    ),
    [recommendationItems, selectedSlots],
  )
  const canShowRecommendationHighlight = showRecommendationHighlight && recommendationByRoom.size > 0
  const needsBuildingSelection = buildings.length > 0 && selectedBuildings.length === 0
  const needsSlotSelection = selectedBuildings.length > 0 && selectedSlots.length === 0

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">BUPT Classroom Planner</p>
          <h1>空教室与个人课表联动查询</h1>
        </div>
        <div className="status-pill">
          <Clock3 size={16} />
          <span>{todayDate}</span>
        </div>
      </header>

      {error ? (
        <div className="notice error">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="workspace">
        <aside className="control-panel">
          <section className="panel">
            <div className="panel-title">
              <KeyRound size={18} />
              <h2>账号</h2>
            </div>
            <label>
              学号
              <input
                value={credentials.account}
                onChange={(event) => updateCredential('account', event.target.value)}
                inputMode="numeric"
                placeholder="留空则使用后端环境变量"
              />
            </label>
            <label>
              教务密码
              <input
                value={credentials.password}
                onChange={(event) => updateCredential('password', event.target.value)}
                type="password"
                placeholder="不会写入本地存储"
              />
            </label>
          </section>

          <section className="panel">
            <div className="panel-title">
              <CalendarDays size={18} />
              <h2>查询条件</h2>
            </div>
            <div className="primary-fields">
              <label>
                日期
                <input
                  type="date"
                  value={todayDate}
                  disabled
                />
              </label>
              <div className="field-group">
                校区
                <div className="campus-options">
                  {(metadata.campuses || []).map((campus) => (
                    <button
                      key={campus.id}
                      type="button"
                      className={campusId === campus.id ? 'active' : ''}
                      onClick={() => selectCampus(campus.id)}
                    >
                      <MapPin size={15} />
                      {campus.name}
                    </button>
                  ))}
                </div>
              </div>
              <label>
                最少座位
                <input
                  type="number"
                  min="0"
                  value={minSeats}
                  onChange={(event) => {
                    setMinSeats(Number(event.target.value))
                    setRecommendations(null)
                  }}
                />
              </label>
            </div>
            <details className="advanced-options">
              <summary>
                <SlidersHorizontal size={15} />
                备用参数
              </summary>
              <div className="advanced-grid">
                <label>
                  学期
                  <input value={termId} onChange={(event) => setTermId(event.target.value)} />
                </label>
                <label>
                  第一周周一
                  <input type="date" value={termStartDate} onChange={(event) => setTermStartDate(event.target.value)} />
                </label>
              </div>
            </details>
          </section>

          <section className="panel action-panel">
            <button type="button" onClick={loadSchedule} disabled={!!loading}>
              {loading === 'schedule' ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
              获取个人课表
            </button>
            <button type="button" onClick={loadClassrooms} disabled={!!loading}>
              {loading === 'classrooms' ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
              查看空教室
            </button>
            <button type="button" className="primary" onClick={runRecommendations} disabled={!!loading}>
              {loading === 'recommendations' ? <Loader2 className="spin" size={17} /> : <Sparkles size={17} />}
              推荐同一教室
            </button>
          </section>
        </aside>

        <section className="main-grid">
          <section className="summary-band">
            <div>
              <span>当天课程</span>
              <strong>{weekState.dayCourses.length}</strong>
            </div>
            <div>
              <span>个人空闲节次</span>
              <strong>{freeSlots.length}</strong>
            </div>
            <div>
              <span>匹配教室</span>
              <strong>{needsBuildingSelection || needsSlotSelection ? 0 : filteredRooms.length}</strong>
            </div>
            <div>
              <span>推荐结果</span>
              <strong>{recommendationItems.length || 0}</strong>
            </div>
          </section>

          <section className="panel wide">
            <div className="panel-heading">
              <div className="panel-title">
                <Clock3 size={18} />
                <h2>节次筛选</h2>
              </div>
              <div className="mini-actions">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedSlots(freeSlots)
                    setRecommendations(null)
                  }}
                >
                  选中空闲
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedSlots([])
                    setRecommendations(null)
                  }}
                >
                  清空
                </button>
              </div>
            </div>
            <div className="filter-toggles">
              <button
                type="button"
                className={usePersonalSchedule ? 'active' : ''}
                onClick={togglePersonalSchedule}
              >
                个人课表 {usePersonalSchedule ? '开' : '关'}
              </button>
              <button
                type="button"
                className={canShowRecommendationHighlight ? 'active' : ''}
                disabled={!recommendationItems.length}
                onClick={() => setShowRecommendationHighlight((current) => !current)}
              >
                推荐高亮 {showRecommendationHighlight ? '开' : '关'}
              </button>
            </div>
            <div className="slot-grid">
              {slotMeta.map((slot) => {
                const personalCourseSlot = weekState.busySlots.includes(slot.index)
                const busy = busySlots.includes(slot.index)
                const selected = selectedSlots.includes(slot.index)
                return (
                  <button
                    key={slot.index}
                    type="button"
                    className={`slot-cell ${busy ? 'busy' : 'free'} ${selected ? 'selected' : ''}`}
                    onClick={() => !busy && toggleSlot(slot.index)}
                    disabled={busy}
                    title={busy ? '个人课表占用' : personalCourseSlot ? '个人课程时间，已纳入筛选' : '个人空闲，可筛选教室'}
                  >
                    <span>{slot.label}</span>
                    <small>{slot.start}-{slot.end}</small>
                  </button>
                )
              })}
            </div>
            <p className="muted">
              第 {weekState.weekNumber || '-'} 周，选中范围：
              {selectedRanges.length ? selectedRanges.map((range) => range.label).join(' / ') : '未选择'}
            </p>
          </section>

          <section className="panel">
            <div className="panel-title">
              <CalendarDays size={18} />
              <h2>当天课程</h2>
            </div>
            <div className="course-list">
              {weekState.dayCourses.length ? weekState.dayCourses.map((course) => (
                <article key={course.id} className="course-row">
                  <div>
                    <strong>{course.name}</strong>
                    <span>{course.teacher || '教师未标注'}</span>
                  </div>
                  <div>
                    <span>{course.time_range}</span>
                    <span>{course.room || '地点未标注'}</span>
                  </div>
                </article>
              )) : (
                <div className="empty-state">当前日期没有已解析课程。</div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-title">
              <Building2 size={18} />
              <h2>教学楼</h2>
            </div>
            <div className="building-list">
              {buildings.length ? buildings.map((building) => (
                <button
                  key={building}
                  type="button"
                  className={selectedBuildings.includes(building) ? 'active' : ''}
                  onClick={() => toggleBuilding(building)}
                >
                  <MapPin size={15} />
                  {displayBuildingName(building)}
                </button>
              )) : <div className="empty-state">获取空教室后可筛选教学楼。</div>}
            </div>
          </section>

          <section className="panel wide">
            <div className="panel-title">
              <CheckCircle2 size={18} />
              <h2>空教室结果</h2>
            </div>
            {classrooms?.provider ? (
              <p className="muted source-note">
                数据源：移动教务 restClassroom 今日空教室
                {recommendationItems.length ? ' · 已计算推荐' : ''}
              </p>
            ) : null}
            <div className="room-list">
              {needsBuildingSelection ? (
                <div className="empty-state">未选择教学楼</div>
              ) : needsSlotSelection ? (
                <div className="empty-state">未选择节次</div>
              ) : (
                filteredRooms.length ? filteredRooms.map((room) => (
                  (() => {
                    const recommendation = canShowRecommendationHighlight ? recommendationByRoom.get(room.id) : null
                    return (
                      <article key={room.id} className={`room-card ${recommendation ? 'recommended' : ''}`}>
                        <div>
                          <strong>{displayBuildingName(room.name)}</strong>
                          <span>
                            {recommendation ? '推荐 · ' : ''}
                            {room.size ? `${room.size} 座` : '座位未知'}
                            {recommendation ? ` · 评分 ${recommendation.score}` : ''}
                          </span>
                        </div>
                        <p>满足所选时间：{selectedRanges.map((range) => range.label).join(' / ')}</p>
                        {recommendation?.longest_range ? (
                          <p>
                            最长连续 {recommendation.longest_range.length} 节：
                            {recommendation.longest_range.start_time}-{recommendation.longest_range.end_time}
                          </p>
                        ) : null}
                        {recommendation ? (
                          <div className="range-tags">
                            {recommendation.ranges.map((range) => (
                              <span key={`${room.id}-${range.start_slot}-${range.end_slot}`}>
                                {range.start_time}-{range.end_time}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    )
                  })()
                )) : (
                  <div className="empty-state">还没有匹配的空教室。先获取数据，或缩小节次/教学楼限制。</div>
                )
              )}
            </div>
          </section>
        </section>
      </div>
    </main>
  )
}

export default App
