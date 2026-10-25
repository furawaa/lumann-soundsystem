// UI language. Every user-visible string in the app lives here.
//
// Values are either a template with {placeholders} or a function, which is what
// Russian plurals need: "1 дубль / 2 дубля / 5 дублей" cannot be expressed by
// interpolation alone.
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from "react";

export type Lang = "ru" | "en";

type Params = Record<string, string | number>;
type Entry = string | ((p: Params) => string);

const STORAGE_KEY = "lumann.lang";

/** 1 дубль / 2 дубля / 5 дублей */
function plural(n: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(n) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

const ru = {
  // shell
  "app.brand": "Lumann Soundsystem",
  "app.new": "+ Новый",
  "app.projects": "Проекты",
  "app.sections": "Разделы",
  "app.noProjects": "пока пусто",
  "app.dismiss": "(нажмите, чтобы скрыть)",
  "app.emptyTitle": "Проекта нет",
  "app.createProject": "Создать проект",
  "app.deleteProject": "Удалить проект",
  "app.deleteProjectConfirm": (p: Params) =>
    `Удалить проект «${p.title}»? Весь звук будет стёрт безвозвратно.`,
  "app.stale": (p: Params) => `${p.n} устарело`,

  "nav.favorites": "Избранное",
  "nav.composes": "Сборки",
  "nav.samples": "Сэмплы",

  // worker
  "worker.loading": "загружается модель Qwen, ~45 с",
  "worker.running": "воркер работает",
  "worker.ready": "воркер готов",
  "worker.error": "воркер: ошибка",
  "worker.paused": (p: Params) => `${p.n} в очереди, на паузе`,
  "worker.stopped": "воркер остановлен",

  // middle panel
  "tab.tracks": "Дорожки",
  "tab.queue": "Очередь",
  "tab.composes": "Сборки",
  "scope.remaining": "всё незаписанное",
  "scope.all": "все сегменты",
  "scope.stale": "только с изменённым текстом",
  "scope.rerecord": "помеченные ⟳",
  "record.start": "Записать",
  "record.stop": "Стоп",
  "record.recording": "Идёт запись",
  "playAll.start": "Автовоспроизведение с первой дорожки",
  "playAll.fromSelected": "Автовоспроизведение с выбранной дорожки",
  "playAll.pause": "Пауза",
  "playAll.resume": "Продолжить",
  "playAll.stop": "Остановить прослушивание",
  "record.markedTitle": "Помечено на перезапись — нажмите, чтобы выбрать эту область",
  "record.pending": "Есть что записать — нажмите, чтобы запустить озвучку",
  "record.startTitle": "Поставить выбранные сегменты в очередь и начать озвучку. Голосу-клону (Qwen) нужно ~45 с на загрузку модели при первом задании.",
  "record.stopSub": "голос Qwen при повторном запуске загрузит модель заново, ~45 с",
  "stats.done": (p: Params) => `${p.done}/${p.total} готово`,
  "stats.stale": (p: Params) => `${p.n} с изменённым текстом`,
  "stats.failed": (p: Params) => `${p.n} с ошибкой`,
  "stats.left": (p: Params) => `осталось ~${p.time}`,
  "stats.total": (p: Params) => `итог ~${p.time}`,
  "stats.totalTitle": "ожидаемая длительность готовой книги",

  // tracks
  "track.play": "Воспроизвести",
  "track.playTake": "Воспроизвести дубль",
  "track.showTakes": "Показать дубли",
  "track.hideTakes": "Скрыть дубли",
  "player.back": "Назад на 5 секунд",
  "player.forward": "Вперёд на 5 секунд",
  "track.movedTitle": "порядковый номер изменился, звук прежний",
  "track.favorite": "В избранное",
  "track.markRerecord": "Пометить на перезапись",
  "track.more": "Ещё",
  "track.recording": "запись…",
  "track.queued": "в очереди",
  "track.staleTag": "текст изменён",
  "track.failedTag": "ошибка",
  "track.overrideTag": "правка",
  "track.takes": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "дубль", "дубля", "дублей")}`,
  "menu.rerecordNow": "Перезаписать сейчас",
  "menu.editText": "Изменить текст…",
  "menu.insertAfter": "Вставить сэмпл",
  "menu.download": "Скачать дорожку",

  // takes
  "take.label": (p: Params) => `дубль ${p.n}`,
  "take.older": "старый текст",
  "take.makeActive": "✓ Сделать активным",
  "take.activeTitle": "активный дубль",
  "take.delete": "Удалить дубль",
  "take.deleteActiveTitle": "нельзя удалить активный дубль",
  "take.deleteConfirm": (p: Params) =>
    `Удалить дубль ${p.n}? Файл будет стёрт безвозвратно.`,
  "take.promoteOutdated": (p: Params) =>
    `Дубль ${p.n} записан по старому тексту.\n\n`
    + "Если сделать его активным, сегмент останется помеченным как «текст изменён» "
    + "и звук не будет соответствовать тексту.\n\nВсё равно сделать активным?",

  // inserts
  "insert.pause": "пауза",
  "insert.seconds": "с",
  "insert.missingFile": "(нет файла)",
  "insert.preview": "Прослушать",
  "insert.delete": "Удалить вставку",
  "insert.drag": "Перетащить: сменить место вставки в дорожках",
  "insert.title": "Вставка после сегмента",
  "insert.typeSilence": "Пауза",
  "insert.typeSample": "Сэмпл",
  "insert.duration": "Длительность, секунд",
  "insert.file": "Файл",
  "insert.noSamples": "Сэмплов ещё нет — загрузите их в разделе «Сэмплы».",
  "insert.add": "Вставить",

  // scattering samples
  "scatter.title": "Разбросать сэмплы",
  "scatter.buttonTitle": "Разбросать случайные сэмплы по книге",
  "scatter.count": "Сколько вставить",
  "scatter.gap": "Минимум между сэмплами, секунд звука",
  "scatter.gapAny": "не важно",
  "scatter.pool": "Из каких сэмплов выбирать",
  "scatter.add": "Разбросать",
  "scatter.working": "Раскидываю…",
  "scatter.placed": (p: Params) =>
    `вставлено: ${p.n} ${plural(Number(p.n), "сэмпл", "сэмпла", "сэмплов")}`,
  "scatter.lastBatch": (p: Params) =>
    `последний разброс: ${p.n} ${plural(Number(p.n), "сэмпл", "сэмпла", "сэмплов")}`,
  "scatter.showOnly": "Показать только их",
  "scatter.showOnlyTitle": "Оставить в дорожках только эти сэмплы и строки, за которыми они стоят",
  "scatter.showAll": "Показать всё",
  "scatter.undo": "Откатить",
  "scatter.undoTitle": "Убрать все сэмплы последнего разброса. Расставленные вручную останутся",
  "scatter.placedFewer": (p: Params) =>
    `вставлено ${p.n} из ${p.asked}: с таким промежутком больше не помещается`,

  // text panel
  "text.original": "Исходный",
  "text.formatted": "Обработанный",
  "text.loading": "Загрузка…",
  "text.saved": "сохранено",
  "text.save": "Сохранить",
  "text.reformat": "Переформатировать…",
  "text.edit": "Редактировать обработанный текст",
  "text.originalReadOnly": "Исходный текст только для чтения — это запись того, "
    + "что было загружено. Правьте обработанный текст: он и есть то, что озвучивается.",
  "text.rederive": "Пересобрать из исходного",
  "text.rederiveTitle": "Заново обработать исходный текст. Ваши правки "
    + "обработанного текста будут потеряны — сначала посмотрите разницу.",
  "text.stopEditing": "Закончить редактирование",
  "text.compare": "Сравнить",
  "text.compareTitle": "Показать слева исходный текст — тот, что был загружён",
  "text.undo": "Отменить правку (⌘Z)",
  "text.redo": "Вернуть правку (⌘Y или ⇧⌘Z)",
  "text.findTitle": "Найти и заменить (⌘F)",
  "text.resetPanes": "Двойной клик — вернуть ширину по умолчанию",

  // find and replace
  "find.placeholder": "Найти",
  "find.replaceWith": "Заменить на",
  "find.replaceWithGroups": "Заменить на ($1 — группа)",
  "find.replace": "Заменить",
  "find.replaceAll": "Заменить всё",
  "find.next": "Следующее совпадение (Enter)",
  "find.prev": "Предыдущее совпадение (Shift+Enter)",
  "find.close": "Закрыть поиск (Esc)",
  "find.none": "нет совпадений",
  "find.badRegex": "не регулярка",
  "find.position": (p: Params) => `${p.n} из ${p.total}`,
  "find.replaced": (p: Params) =>
    `заменено: ${p.n} ${plural(Number(p.n), "совпадение", "совпадения", "совпадений")}`,
  "find.caseSensitive": "С учётом регистра: «Оля» не найдёт «оля»",
  "find.wholeWord": "Слово целиком: «он» не найдёт «она»",
  "find.regex": "Регулярное выражение. Кириллица — это \\p{L}, а не \\w",
  "find.foldYo": "е и ё — одна буква: «пришел» найдёт «пришёл». "
    + "Ё в тексте при замене сохраняется",

  // format diff
  "format.title": "Форматирование правок",
  "format.computing": "Применяю правила…",
  "format.pick": "Выберите, какая версия пойдёт в проект",
  "format.noChanges": "Правила ничего не меняют — версии совпадают",
  "format.yours": "Ваш текст",
  "format.formatted": "После форматирования",
  "format.changedLines": "изменено абзацев",
  "format.addedLines": "добавлено абзацев",
  "format.deletedLines": "удалено абзацев",
  "format.unchangedLines": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "абзац", "абзаца", "абзацев")} без изменений`,
  "format.keepMine": "Оставить как есть",
  "format.useFormatted": "Применить форматирование",

  // voices
  "voices.title": "Голоса",
  "voices.hint": "Голос eSpeak — это набор настроек. Голос-клон (Qwen3-TTS) — запись плюс её точный текст.",
  "voices.pickTitle": "Каким голосом озвучивать",
  "voices.none": "голос не выбран",
  "voices.manage": "Голоса…",
  "voices.use": "Озвучивать этим голосом",
  "voices.missing": "нет файла",
  "voices.delete": "Удалить голос",
  "voices.builtinKept": "Встроенные голоса удалить нельзя",
  "voices.deleteConfirm": (p: Params) =>
    `Удалить голос «${p.name}»? Записанные им дубли останутся на месте.`,
  "voices.addNew": "+ Добавить голос",
  "voices.addEspeak": "+ Голос eSpeak",
  "voices.addClone": "+ Голос-клон (Qwen3-TTS)",
  "voices.engineEspeak": "eSpeak",
  "voices.engineQwen": "клон Qwen",
  "voices.language": "Язык",
  "voices.variant": "Вариант",
  "voices.variantNone": "по умолчанию",
  "voices.speed": "Скорость, слов/мин",
  "voices.pitch": "Высота",
  "voices.espeakHint": "Прослушать голос можно сразу после добавления. Настройки меняются в любой момент.",
  "voices.espeakNotFound": "espeak-ng не найден",
  "voices.espeakMissing": "eSpeak NG не установлен, поэтому встроенные голоса не работают. Установите его и перезапустите сервер:",
  "voices.qwenMissing": "Для клонирования нужен Qwen3-TTS — скачайте его ниже. Голос можно добавить уже сейчас, записывать им можно будет после загрузки.",
  "voices.rename": "Переименовать",
  "voices.renameHint": "Enter — сохранить, Esc — отменить. Пустое название — название по настройкам голоса.",
  "voices.renameAuto": "пусто — название по настройкам",
  "qwen.title": "Qwen3-TTS — клонирование голоса",
  "qwen.tagReady": "установлен",
  "qwen.tagBusy": "загрузка",
  "qwen.tagOff": "не установлен",
  "qwen.notInstalled": "Не установлен. Нужен только для голосов-клонов; голоса eSpeak работают без него.",
  "qwen.what": "Загрузка: пакеты PyTorch и qwen-tts (около 1,5 ГБ) и модель (4,2 ГБ). Всё ляжет в одну папку и удаляется одной кнопкой.",
  "qwen.needsModel": "Пакеты qwen-tts уже установлены. «Скачать» загрузит только модель (4,2 ГБ).",
  "qwen.partial": "Загружен не полностью. «Продолжить» докачает недостающее, «Удалить» уберёт всё.",
  "qwen.installingPackages": "Устанавливаются пакеты (PyTorch и другие), это несколько минут…",
  "qwen.downloading": (p: Params) => `Загружается модель: ${p.done} из ${p.total}`,
  "qwen.installed": (p: Params) => `Установлен, занимает ${p.size}.`,
  "qwen.installedOutside": "Установлен вне приложения.",
  "qwen.outsideNote": "Пакеты qwen-tts установлены не приложением, поэтому «Удалить» их не тронет — удалите их через pip.",
  "qwen.download": "Скачать",
  "qwen.resume": "Продолжить",
  "qwen.delete": "Удалить",
  "qwen.deleteConfirm": "Удалить Qwen3-TTS (пакеты и модель)? Запись будет остановлена. Голоса-клоны останутся, но записывать ими можно будет только после новой загрузки.",
  "voices.add": "Добавить",
  "voices.adding": "Добавляю…",
  "voices.name": "Название",
  "voices.namePlaceholder": "как отличать его в списке",
  "voices.file": "Референсные записи (можно выбрать несколько)",
  "voices.refText": "Текст записи",
  "voices.refTextFor": (p: Params) => `Текст записи «${p.name}»`,
  "voices.refTextPlaceholder": "Слово в слово то, что произносится в файле",
  "voices.clipCount": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "запись", "записи", "записей")}`,
  "voices.addClips": "+ Добавить записи",
  "voices.deleteClip": "Удалить запись",
  "voices.lastClip": "Последнюю запись удалить нельзя — голосу нужна хотя бы одна",
  "voices.useClip": "Озвучивать этой записью",
  "voices.useJoined": "Озвучивать всеми записями сразу",
  "voices.joined": "Все вместе",
  "voices.joinedHint": "Записи склеиваются в один длинный референс, тексты — по порядку.",
  "voices.refTextHint": "Клонирование сопоставляет текст со звуком. Неточный текст "
    + "не вызовет ошибки — он просто испортит все дубли, поэтому перепишите фразу "
    + "дословно, со всеми оговорками.",
  "take.voice": (p: Params) => `голос: ${p.name}`,

  // queue
  "queue.empty": "Очередь пуста",
  "queue.emptyHint": "Нажмите «Записать», чтобы поставить сегменты в очередь.",
  "queue.count": (p: Params) => `${p.n} в очереди`,
  "queue.fallbackRate": " · оценка по умолчанию, 0,15 с/символ",
  "queue.clear": "Очистить очередь",
  "queue.clearTitle": "Убрать всё из очереди, записанное останется",
  "queue.chars": (p: Params) => `${p.n} зн.`,
  "queue.rerecordGroup": "На перезапись",
  "nav.queue": "Очередь",
  "queue.overviewTitle": "Общая очередь",
  "queue.overviewHint": "Здесь появятся книги, которым есть что озвучивать.",
  "queue.rule": "Порядок озвучки: сначала всё, помеченное на перезапись — в любой "
    + "книге; потом первый проход. Внутри каждой из этих групп книги идут в том "
    + "порядке, в каком они стоят ниже, а внутри книги — по порядку текста. "
    + "Перетащите книгу за ручку, чтобы сменить порядок: он же решает, чья "
    + "перезапись пойдёт первой, если их ждут сразу две книги.",
  "queue.theOrder": "Порядок записи",
  "queue.stopAll": "Стоп всё",
  "queue.stopAllTitle": "Остановить озвучку во всех книгах и остановить воркер",
  "queue.dragBook": "Перетащить: сменить место книги в очереди",
  "queue.pauseBook": "Пауза",
  "queue.pauseBookTitle": "Приостановить эту книгу; остальные продолжат",
  "queue.resumeBook": "Продолжить",
  "queue.resumeBookTitle": "Вернуть эту книгу в очередь",
  "queue.bookProgress": (p: Params) =>
    `${p.done}/${p.total} готово · ${p.queued} в очереди`,
  "queue.scopeProject": "Эта книга",
  "queue.scopeGlobal": "Все книги",
  "queue.emptyGlobal": "Очередь пуста во всех книгах",
  "queue.countBooks": (p: Params) =>
    `${p.n} в очереди · ${p.books} ${plural(Number(p.books), "книга", "книги", "книг")}`,
  "queue.thisBook": "эта книга",
  "queue.pausedTag": "на паузе",
  "queue.openBook": (p: Params) => `Открыть «${p.title}»`,
  "queue.firstPassGroup": "Первая запись",
  "queue.remove": "Убрать из очереди",
  "track.notRecorded": "не записано",
  "track.recordThis": "Записать этот трек",

  // reformat
  "reformat.title": "Переформатирование",
  "reformat.fromFormatted": "Правки внесены в обработанный текст. Исходный текст не "
    + "изменится — он остаётся записью того, что было загружено.",
  "reformat.computing": "Считаю разницу…",
  "reformat.apply": "Применить",
  "reformat.applying": "Применяю…",
  "reformat.cancel": "Отмена",
  "reformat.willRerecord": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "сегмент", "сегмента", "сегментов")} с записанным `
    + "звуком придётся перезаписать",
  "reformat.noHarm": "записанный звук не пострадает",
  "reformat.unchanged": "без изменений",
  "reformat.moved": "сдвинуто",
  "reformat.changed": "текст изменён",
  "reformat.new": "новых",
  "reformat.deleted": "удаляется",
  "reformat.kindUnchanged": "без изменений",
  "reformat.kindMoved": "сдвинут",
  "reformat.kindChanged": "текст изменён",
  "reformat.kindNew": "новый",
  "reformat.kindDeleted": "удалён",
  "reformat.emptyFilter": "Ничего в этой категории.",
  "reformat.deletedWithAudio": (p: Params) =>
    `${p.n} удаляемых сегмента содержат запись. Звук не стирается — он переедет в `,
  "reformat.overrideConflict": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "сегмент", "сегмента", "сегментов")} с ручной правкой `
    + "текста: правка сохранена и имеет приоритет над новым исходником — проверьте их.",
  "reformat.insertReview": (p: Params) =>
    `${p.n} ${plural(Number(p.n), "вставка была", "вставки были", "вставок были")} `
    + "привязаны к удалённому сегменту и переехали к предыдущему — проверьте их положение.",

  // new project
  "new.title": "Новый проект",
  "new.name": "Название",
  "new.namePlaceholder": "Глава 1",
  "new.text": "Текст",
  "new.textPlaceholder": "Вставьте текст или перетащите .txt сюда",
  "new.hint": "Абзац начинается со строки с отступом; строки без отступа — "
    + "продолжение. Так текст и будет разбит на сегменты.",
  "new.size": (p: Params) => `${p.chars} знаков · примерно ${p.minutes} мин звука`,
  "new.create": "Создать",
  "new.creating": "Создаю…",

  // edit text
  "edit.title": (p: Params) => `Текст сегмента ${p.index}`,
  "edit.reset": "Вернуть исходный",
  "edit.notice": "Записанный звук перестанет соответствовать тексту: сегмент будет "
    + "помечен как «текст изменён», а дубли — как записанные по старому тексту. "
    + "Ничего не удаляется, всё остаётся слушаемым.",
  "edit.hint": "Правка живёт отдельно от исходника и переживает переформатирование.",

  // composes
  "compose.pickProject": "Выберите проект",
  "compose.title": "Сборки",
  "compose.makeM4a": "Собрать m4a",
  "compose.makeWav": "wav",
  "compose.wavTitle": "Быстро и без потерь",
  "compose.empty": "Сборок пока нет",
  "compose.emptyHint": "m4a показывает настоящий прогресс. wav собирается за секунду, "
    + "без потерь.",
  "compose.parts": (p: Params) => `${p.n} фрагм.`,
  "compose.skipped": (p: Params) => `${p.n} без звука пропущено`,
  "compose.download": "Скачать",
  "compose.delete": "Удалить сборку",
  "compose.progress": (p: Params) => `${p.percent}% из ${p.total}`,
  "compose.copying": "склеиваю без перекодирования — это займёт секунду",
  "compose.usage": (p: Params) =>
    `звук: ${p.active} активных дублей, ${p.archived} в архиве`,
  "compose.usageComposes": (p: Params) => `, ${p.size} сборок`,
  "compose.usageTrash": (p: Params) => `, ${p.size} в корзине`,
  "compose.prune": "Удалить неактивные дубли",
  "compose.pruneConfirm": "Удалить все неактивные дубли? Активные останутся. "
    + "Это необратимо.",
  "compose.pruneDone": (p: Params) =>
    `Удалено дублей: ${p.removed}, освобождено ${p.freed}`,

  // samples
  "samples.title": "Сэмплы",
  "samples.upload": "Загрузить",
  "samples.empty": "Сэмплов нет",
  "samples.emptyHint": "Короткие звуки, которые можно вставлять между сегментами.",
  "samples.deleteConfirm": (p: Params) => `Удалить сэмпл ${p.name}?`,

  // favorites
  "favorites.title": "Избранное",
  "favorites.empty": "Избранного нет",
  "favorites.emptyHint": "Отметьте удачный дубль значком ♥ — он появится здесь, "
    + "из всех проектов.",
  "favorites.noAudio": "нет звука",

  // generic
  "common.close": "Закрыть",
  "common.cancel": "Отмена",
  "common.language": "Язык интерфейса",
  "common.accent": "Цвет акцента",
  "accent.blue": "Синий",
  "accent.green": "Зелёный",

  // units
  "unit.seconds": (p: Params) => `${p.n} с`,
  "unit.minutes": (p: Params) => `${p.n} мин`,
  "unit.hours": (p: Params) => `${p.h} ч ${p.m} мин`,
  "unit.mb": (p: Params) => `${p.n} МБ`,
  "unit.gb": (p: Params) => `${p.n} ГБ`,
  "unit.none": "—",
} satisfies Record<string, Entry>;

export type Key = keyof typeof ru;

const en: Record<Key, Entry> = {
  "app.brand": "Lumann Soundsystem",
  "app.new": "+ New",
  "app.projects": "Projects",
  "app.sections": "Sections",
  "app.noProjects": "nothing yet",
  "app.dismiss": "(click to dismiss)",
  "app.emptyTitle": "No project",
  "app.createProject": "Create a project",
  "app.deleteProject": "Delete project",
  "app.deleteProjectConfirm": (p) =>
    `Delete “${p.title}”? All of its audio will be erased for good.`,
  "app.stale": (p) => `${p.n} stale`,

  "nav.favorites": "Favorites",
  "nav.composes": "Composes",
  "nav.samples": "Samples",

  "worker.loading": "loading Qwen model, ~45 s",
  "worker.running": "worker running",
  "worker.ready": "worker ready",
  "worker.error": "worker: error",
  "worker.paused": (p) => `${p.n} queued, paused`,
  "worker.stopped": "worker stopped",

  "tab.tracks": "Tracks",
  "tab.queue": "Queue",
  "tab.composes": "Composes",
  "scope.remaining": "everything unrecorded",
  "scope.all": "all segments",
  "scope.stale": "changed text only",
  "scope.rerecord": "marked ⟳",
  "record.start": "Record",
  "record.stop": "Stop",
  "record.recording": "Recording",
  "playAll.start": "Autoplay from the first track",
  "playAll.fromSelected": "Autoplay from selected track",
  "playAll.pause": "Pause",
  "playAll.resume": "Resume",
  "playAll.stop": "Stop playback",
  "record.markedTitle": "Marked for re-recording — click to select that scope",
  "record.pending": "There is work waiting — press to start narrating",
  "record.startTitle": "Queue the selected segments and start narrating. A cloned (Qwen) voice loads its model on the first job, ~45 s.",
  "record.stopSub": "a Qwen voice reloads its model on restart (~45 s)",
  "stats.done": (p) => `${p.done}/${p.total} done`,
  "stats.stale": (p) => `${p.n} with changed text`,
  "stats.failed": (p) => `${p.n} failed`,
  "stats.left": (p) => `~${p.time} left`,
  "stats.total": (p) => `~${p.time} total`,
  "stats.totalTitle": "projected length of the finished book",

  "track.play": "Play",
  "track.playTake": "Play take",
  "track.showTakes": "Show takes",
  "track.hideTakes": "Hide takes",
  "player.back": "Back 5 seconds",
  "player.forward": "Forward 5 seconds",
  "track.movedTitle": "index changed, audio is unchanged",
  "track.favorite": "Favorite",
  "track.markRerecord": "Mark for re-recording",
  "track.more": "More",
  "track.recording": "recording…",
  "track.queued": "queued",
  "track.staleTag": "text changed",
  "track.failedTag": "failed",
  "track.overrideTag": "edited",
  "track.takes": (p) => `${p.n} ${Number(p.n) === 1 ? "take" : "takes"}`,
  "menu.rerecordNow": "Re-record now",
  "menu.editText": "Edit text…",
  "menu.insertAfter": "Insert sample",
  "menu.download": "Download track",

  "take.label": (p) => `take ${p.n}`,
  "take.older": "older text",
  "take.makeActive": "✓ Make active",
  "take.activeTitle": "active take",
  "take.delete": "Delete take",
  "take.deleteActiveTitle": "cannot delete the active take",
  "take.deleteConfirm": (p) => `Delete take ${p.n}? The file is erased for good.`,
  "take.promoteOutdated": (p) =>
    `Take ${p.n} was recorded against older text.\n\n`
    + "Making it active leaves this segment marked “text changed”, and the audio "
    + "will not match the text.\n\nMake it active anyway?",

  "insert.pause": "pause",
  "insert.seconds": "s",
  "insert.missingFile": "(file missing)",
  "insert.preview": "Preview",
  "insert.delete": "Delete insert",
  "insert.drag": "Drag to move this insert elsewhere in the timeline",
  "insert.title": "Insert after segment",
  "insert.typeSilence": "Silence",
  "insert.typeSample": "Sample",
  "insert.duration": "Duration, seconds",
  "insert.file": "File",
  "insert.noSamples": "No samples yet — upload some under “Samples”.",
  "insert.add": "Insert",

  "scatter.title": "Scatter samples",
  "scatter.buttonTitle": "Scatter random samples across the book",
  "scatter.count": "How many",
  "scatter.gap": "Minimum between samples, seconds of audio",
  "scatter.gapAny": "no minimum",
  "scatter.pool": "Pick from these samples",
  "scatter.add": "Scatter",
  "scatter.working": "Placing…",
  "scatter.placed": (p) => `placed ${p.n} sample${Number(p.n) === 1 ? "" : "s"}`,
  "scatter.lastBatch": (p) => `last scatter: ${p.n} sample${Number(p.n) === 1 ? "" : "s"}`,
  "scatter.showOnly": "Show only these",
  "scatter.showOnlyTitle": "Keep only the scattered samples and the lines they follow",
  "scatter.showAll": "Show everything",
  "scatter.undo": "Undo",
  "scatter.undoTitle": "Remove every sample of the last scatter. Hand-placed inserts stay",
  "scatter.placedFewer": (p) =>
    `placed ${p.n} of ${p.asked}: no room for more at that spacing`,

  "text.original": "Original",
  "text.formatted": "Formatted",
  "text.loading": "Loading…",
  "text.saved": "saved",
  "text.save": "Save",
  "text.reformat": "Reformat…",
  "text.edit": "Edit the formatted text",
  "text.originalReadOnly": "The original is read-only — it is the record of what was "
    + "imported. Edit the formatted text instead: that is what gets spoken.",
  "text.rederive": "Re-derive from original",
  "text.rederiveTitle": "Format the original again. Your edits to the formatted text "
    + "will be lost — look at the diff first.",
  "text.stopEditing": "Stop editing",
  "text.compare": "Compare",
  "text.compareTitle": "Show the original text on the left — the one that was imported",
  "text.undo": "Undo (⌘Z)",
  "text.redo": "Redo (⌘Y or ⇧⌘Z)",
  "text.findTitle": "Find and replace (⌘F)",
  "text.resetPanes": "Double-click to reset the width",

  "find.placeholder": "Find",
  "find.replaceWith": "Replace with",
  "find.replaceWithGroups": "Replace with ($1 is a group)",
  "find.replace": "Replace",
  "find.replaceAll": "Replace all",
  "find.next": "Next match (Enter)",
  "find.prev": "Previous match (Shift+Enter)",
  "find.close": "Close find (Esc)",
  "find.none": "no matches",
  "find.badRegex": "not a regex",
  "find.position": (p) => `${p.n} of ${p.total}`,
  "find.replaced": (p) => `replaced ${p.n} match${Number(p.n) === 1 ? "" : "es"}`,
  "find.caseSensitive": "Match case: “Оля” will not find “оля”",
  "find.wholeWord": "Whole word: “он” will not find “она”",
  "find.regex": "Regular expression. Cyrillic is \\p{L}, not \\w",
  "find.foldYo": "Treat е and ё as one letter: “пришел” finds “пришёл”. "
    + "The ё in the text survives the replacement",

  // format diff
  "format.title": "Format the edit",
  "format.computing": "Applying the rules…",
  "format.pick": "Pick the version that goes into the project",
  "format.noChanges": "The rules change nothing — the versions are identical",
  "format.yours": "Your text",
  "format.formatted": "After formatting",
  "format.changedLines": "paragraphs changed",
  "format.addedLines": "paragraphs added",
  "format.deletedLines": "paragraphs deleted",
  "format.unchangedLines": (p: Params) => `${p.n} unchanged paragraph${p.n === 1 ? "" : "s"}`,
  "format.keepMine": "Keep mine",
  "format.useFormatted": "Apply formatting",

  // voices
  "voices.title": "Voices",
  "voices.hint": "An eSpeak voice is a few settings. A cloned voice (Qwen3-TTS) is a recording plus its exact transcript.",
  "voices.pickTitle": "Which voice to narrate with",
  "voices.none": "no voice selected",
  "voices.manage": "Voices…",
  "voices.use": "Narrate with this voice",
  "voices.missing": "file missing",
  "voices.delete": "Delete voice",
  "voices.builtinKept": "Built-in voices cannot be deleted",
  "voices.deleteConfirm": (p) =>
    `Delete the voice "${p.name}"? Takes recorded with it stay where they are.`,
  "voices.addNew": "+ Add a voice",
  "voices.addEspeak": "+ eSpeak voice",
  "voices.addClone": "+ Cloned voice (Qwen3-TTS)",
  "voices.engineEspeak": "eSpeak",
  "voices.engineQwen": "Qwen clone",
  "voices.language": "Language",
  "voices.variant": "Variant",
  "voices.variantNone": "default",
  "voices.speed": "Speed, words/min",
  "voices.pitch": "Pitch",
  "voices.espeakHint": "You can play a sample right after adding it, and change the settings any time.",
  "voices.espeakNotFound": "espeak-ng not found",
  "voices.espeakMissing": "eSpeak NG is not installed, so the built-in voices cannot speak. Install it and restart the server:",
  "voices.qwenMissing": "Cloning needs Qwen3-TTS — download it below. You can add the voice now and record with it once the download is done.",
  "voices.rename": "Rename",
  "voices.renameHint": "Enter saves, Esc cancels. Leave it empty to name the voice after its settings.",
  "voices.renameAuto": "empty — named after its settings",
  "qwen.title": "Qwen3-TTS voice cloning",
  "qwen.tagReady": "installed",
  "qwen.tagBusy": "downloading",
  "qwen.tagOff": "not installed",
  "qwen.notInstalled": "Not installed. Only cloned voices need it; eSpeak voices work without it.",
  "qwen.what": "Downloads the PyTorch and qwen-tts packages (about 1.5 GB) and the model (4.2 GB). It all goes into one folder, and Delete removes all of it.",
  "qwen.needsModel": "The qwen-tts packages are already installed. Download fetches only the model (4.2 GB).",
  "qwen.partial": "Partly downloaded. Resume fetches what is missing; Delete removes everything.",
  "qwen.installingPackages": "Installing packages (PyTorch and others), this takes a few minutes…",
  "qwen.downloading": (p) => `Downloading the model: ${p.done} of ${p.total}`,
  "qwen.installed": (p) => `Installed, using ${p.size}.`,
  "qwen.installedOutside": "Installed outside the app.",
  "qwen.outsideNote": "The qwen-tts packages were not installed by the app, so Delete leaves them alone; remove them with pip.",
  "qwen.download": "Download",
  "qwen.resume": "Resume",
  "qwen.delete": "Delete",
  "qwen.deleteConfirm": "Delete Qwen3-TTS (packages and model)? Recording will stop. Cloned voices stay, but they can only record again after a new download.",
  "voices.add": "Add",
  "voices.adding": "Adding…",
  "voices.name": "Name",
  "voices.namePlaceholder": "how to tell it apart in the list",
  "voices.file": "Reference clips (several at once is fine)",
  "voices.refText": "Transcript",
  "voices.refTextFor": (p) => `Transcript of "${p.name}"`,
  "voices.refTextPlaceholder": "Word for word what the clip says",
  "voices.clipCount": (p) => `${p.n} clip${p.n === 1 ? "" : "s"}`,
  "voices.addClips": "+ Add clips",
  "voices.deleteClip": "Delete clip",
  "voices.lastClip": "The last clip cannot go — a voice needs at least one",
  "voices.useClip": "Narrate with this clip",
  "voices.useJoined": "Narrate with all clips at once",
  "voices.joined": "All together",
  "voices.joinedHint": "The clips are concatenated into one long reference, transcripts in order.",
  "voices.refTextHint": "Cloning matches the transcript against the audio. A wrong one "
    + "raises no error — it just degrades every take, so type the line out exactly, "
    + "false starts and all.",
  "take.voice": (p) => `voice: ${p.name}`,

  "queue.empty": "Queue is empty",
  "queue.emptyHint": "Press Record to queue up segments.",
  "queue.count": (p) => `${p.n} queued`,
  "queue.fallbackRate": " · default estimate, 0.15 s/char",
  "queue.clear": "Clear queue",
  "queue.clearTitle": "Empty the queue; recorded audio stays",
  "queue.chars": (p) => `${p.n} ch.`,
  "queue.rerecordGroup": "To re-record",
  "nav.queue": "Queue",
  "queue.overviewTitle": "All books",
  "queue.overviewHint": "Books with something to narrate show up here.",
  "queue.rule": "Recording order: everything marked for re-recording first, in "
    + "any book; then first-pass work. Within each of those, books go in the "
    + "order they stand below, and within a book, in the order of the text. "
    + "Drag a book by its grip to reorder — that order also decides whose "
    + "re-record runs first when two books are waiting for one.",
  "queue.theOrder": "Recording order",
  "queue.stopAll": "Stop all",
  "queue.stopAllTitle": "Stop narrating every book and stop the worker",
  "queue.dragBook": "Drag to move this book in the queue",
  "queue.pauseBook": "Pause",
  "queue.pauseBookTitle": "Pause this book; the others carry on",
  "queue.resumeBook": "Resume",
  "queue.resumeBookTitle": "Put this book back in the queue",
  "queue.bookProgress": (p) => `${p.done}/${p.total} done · ${p.queued} queued`,
  "queue.scopeProject": "This book",
  "queue.scopeGlobal": "All books",
  "queue.emptyGlobal": "Nothing queued in any book",
  "queue.countBooks": (p) =>
    `${p.n} queued · ${p.books} book${Number(p.books) === 1 ? "" : "s"}`,
  "queue.thisBook": "this book",
  "queue.pausedTag": "paused",
  "queue.openBook": (p) => `Open “${p.title}”`,
  "queue.firstPassGroup": "First pass",
  "queue.remove": "Remove from queue",
  "track.notRecorded": "not recorded",
  "track.recordThis": "Record this track",

  "reformat.title": "Reformat",
  "reformat.fromFormatted": "You edited the formatted text. The original is left "
    + "untouched — it stays the record of what was imported.",
  "reformat.computing": "Computing the diff…",
  "reformat.apply": "Apply",
  "reformat.applying": "Applying…",
  "reformat.cancel": "Cancel",
  "reformat.willRerecord": (p) =>
    `${p.n} ${Number(p.n) === 1 ? "segment" : "segments"} with recorded audio will `
    + "need re-recording",
  "reformat.noHarm": "no recorded audio is affected",
  "reformat.unchanged": "unchanged",
  "reformat.moved": "moved",
  "reformat.changed": "text changed",
  "reformat.new": "new",
  "reformat.deleted": "deleted",
  "reformat.kindUnchanged": "unchanged",
  "reformat.kindMoved": "moved",
  "reformat.kindChanged": "text changed",
  "reformat.kindNew": "new",
  "reformat.kindDeleted": "deleted",
  "reformat.emptyFilter": "Nothing in this category.",
  "reformat.deletedWithAudio": (p) =>
    `${p.n} of the deleted segments have recordings. The audio is not erased — `
    + "it moves to ",
  "reformat.overrideConflict": (p) =>
    `${p.n} ${Number(p.n) === 1 ? "segment has" : "segments have"} a manual text `
    + "edit: it is kept and wins over the new source — check them.",
  "reformat.insertReview": (p) =>
    `${p.n} ${Number(p.n) === 1 ? "insert was" : "inserts were"} attached to a deleted `
    + "segment and moved to the previous one — check where they landed.",

  "new.title": "New project",
  "new.name": "Title",
  "new.namePlaceholder": "Chapter 1",
  "new.text": "Text",
  "new.textPlaceholder": "Paste the text, or drop a .txt here",
  "new.hint": "A paragraph starts on an indented line; flush-left lines continue it. "
    + "That is how the text will be split into segments.",
  "new.size": (p) => `${p.chars} characters · about ${p.minutes} min of audio`,
  "new.create": "Create",
  "new.creating": "Creating…",

  "edit.title": (p) => `Text of segment ${p.index}`,
  "edit.reset": "Restore original",
  "edit.notice": "The recorded audio will no longer match the text: the segment gets "
    + "marked “text changed” and its takes “recorded against older text”. Nothing is "
    + "deleted; everything stays playable.",
  "edit.hint": "The edit lives separately from the source and survives reformatting.",

  "compose.pickProject": "Pick a project",
  "compose.title": "Composes",
  "compose.makeM4a": "Compose m4a",
  "compose.makeWav": "wav",
  "compose.wavTitle": "Fast and lossless",
  "compose.empty": "No composes yet",
  "compose.emptyHint": "m4a shows real progress. wav is done in a second, lossless.",
  "compose.parts": (p) => `${p.n} parts`,
  "compose.skipped": (p) => `${p.n} skipped, no audio`,
  "compose.download": "Download",
  "compose.delete": "Delete compose",
  "compose.progress": (p) => `${p.percent}% of ${p.total}`,
  "compose.copying": "concatenating without re-encoding — about a second",
  "compose.usage": (p) => `audio: ${p.active} active takes, ${p.archived} archived`,
  "compose.usageComposes": (p) => `, ${p.size} composes`,
  "compose.usageTrash": (p) => `, ${p.size} in trash`,
  "compose.prune": "Delete non-active takes",
  "compose.pruneConfirm": "Delete every non-active take? Active ones stay. "
    + "This cannot be undone.",
  "compose.pruneDone": (p) => `Deleted ${p.removed} takes, freed ${p.freed}`,

  "samples.title": "Samples",
  "samples.upload": "Upload",
  "samples.empty": "No samples",
  "samples.emptyHint": "Short sounds you can drop between segments.",
  "samples.deleteConfirm": (p) => `Delete sample ${p.name}?`,

  "favorites.title": "Favorites",
  "favorites.empty": "Nothing favorited",
  "favorites.emptyHint": "Mark a good take with ♥ and it shows up here, "
    + "across all projects.",
  "favorites.noAudio": "no audio",

  "common.close": "Close",
  "common.cancel": "Cancel",
  "common.language": "Interface language",
  "common.accent": "Accent colour",
  "accent.blue": "Blue",
  "accent.green": "Green",

  "unit.seconds": (p) => `${p.n} s`,
  "unit.minutes": (p) => `${p.n} min`,
  "unit.hours": (p) => `${p.h} h ${p.m} min`,
  "unit.mb": (p) => `${p.n} MB`,
  "unit.gb": (p) => `${p.n} GB`,
  "unit.none": "—",
};

const DICTS: Record<Lang, Record<Key, Entry>> = { ru, en };

export type Translate = (key: Key, params?: Params) => string;

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
}

const Context = createContext<I18n | null>(null);

/** English unless the user switched to Russian with the toggle. */
function detect(): Lang {
  return localStorage.getItem(STORAGE_KEY) === "ru" ? "ru" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detect);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLangState(next);
  }, []);

  const t = useCallback<Translate>((key, params) => {
    const entry = DICTS[lang][key] ?? ru[key];
    if (typeof entry === "function") return entry(params ?? {});
    return params
      ? entry.replace(/\{(\w+)\}/g, (_m, name: string) => String(params[name] ?? ""))
      : entry;
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}

export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang-toggle" title={t("common.language")}>
      {(["ru", "en"] as Lang[]).map((code) => (
        <button
          key={code}
          className={code === lang ? "on" : ""}
          onClick={() => setLang(code)}
          aria-pressed={code === lang}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
