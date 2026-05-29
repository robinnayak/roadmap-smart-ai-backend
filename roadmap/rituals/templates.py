TONES = ("bro", "gentle", "soft_girl", "coach")


def _tones(*, bro, gentle, soft_girl, coach):
    return {
        "bro": bro,
        "gentle": gentle,
        "soft_girl": soft_girl,
        "coach": coach,
    }


TRIGGER_MESSAGE_TEMPLATES = {
    "morning": [
        {"id": "morning_bro_01", "tone": "bro", "message": "Ayo boss, up early today. That's different. Let's go."},
        {"id": "morning_bro_02", "tone": "bro", "message": "Morning window is open. Take the first clean rep before the day gets loud."},
        {"id": "morning_gentle_01", "tone": "gentle", "message": "You're up early. That's really nice to see. Good morning."},
        {"id": "morning_gentle_02", "tone": "gentle", "message": "Morning is here. Start gently, then choose one clear thing."},
        {"id": "morning_soft_girl_01", "tone": "soft_girl", "message": "You woke up early today. That made my morning."},
        {"id": "morning_soft_girl_02", "tone": "soft_girl", "message": "Good morning, lovely. Start soft and keep one tiny promise."},
        {"id": "morning_coach_01", "tone": "coach", "message": "Early. Good. Use it."},
        {"id": "morning_coach_02", "tone": "coach", "message": "Morning block. Set the standard now."},
    ],
    "afternoon": [
        {"id": "afternoon_bro_01", "tone": "bro", "message": "Afternoon reset, boss. Pick the highest-value move and get back in control."},
        {"id": "afternoon_bro_02", "tone": "bro", "message": "Midday check. The day is still yours if you tighten up now."},
        {"id": "afternoon_gentle_01", "tone": "gentle", "message": "It's afternoon. Take a steady breath and return to one useful step."},
        {"id": "afternoon_gentle_02", "tone": "gentle", "message": "The day is halfway open. You can still make it kind and focused."},
        {"id": "afternoon_soft_girl_01", "tone": "soft_girl", "message": "Afternoon reset. Tiny sip of focus, then one pretty little move."},
        {"id": "afternoon_soft_girl_02", "tone": "soft_girl", "message": "Midday softness counts too. Come back to yourself and keep going."},
        {"id": "afternoon_coach_01", "tone": "coach", "message": "Afternoon. Reset focus. Execute the highest-value task."},
        {"id": "afternoon_coach_02", "tone": "coach", "message": "Midday checkpoint. Cut drift. Continue."},
    ],
    "evening": [
        {"id": "evening_bro_01", "tone": "bro", "message": "Evening window. Finish one thing clean before the day closes."},
        {"id": "evening_bro_02", "tone": "bro", "message": "Evening check, bro. No spiral. Just land the next move."},
        {"id": "evening_gentle_01", "tone": "gentle", "message": "It's evening. Close one loop gently and let the day settle."},
        {"id": "evening_gentle_02", "tone": "gentle", "message": "Evening is here. Choose one small close and give yourself peace."},
        {"id": "evening_soft_girl_01", "tone": "soft_girl", "message": "Evening reset. Tuck one task in nicely before you exhale."},
        {"id": "evening_soft_girl_02", "tone": "soft_girl", "message": "Soft evening check. Close one little loop and feel the day calm down."},
        {"id": "evening_coach_01", "tone": "coach", "message": "Evening. Close the loop. Finish one action."},
        {"id": "evening_coach_02", "tone": "coach", "message": "Day is narrowing. Complete what matters."},
    ],
    "night": [
        {"id": "night_bro_01", "tone": "bro", "message": "Night check. Land the day, protect tomorrow, and shut it down clean."},
        {"id": "night_bro_02", "tone": "bro", "message": "Night mode, boss. Reset the board and let tomorrow inherit a cleaner plan."},
        {"id": "night_gentle_01", "tone": "gentle", "message": "It's night. Let today land gently and make tomorrow a little lighter."},
        {"id": "night_gentle_02", "tone": "gentle", "message": "Night is here. Close softly, release what is done, and rest."},
        {"id": "night_soft_girl_01", "tone": "soft_girl", "message": "Night reset, lovely. Tuck the day in and let tomorrow feel cared for."},
        {"id": "night_soft_girl_02", "tone": "soft_girl", "message": "The day is closing. Be soft with yourself and set down what you can."},
        {"id": "night_coach_01", "tone": "coach", "message": "Night. Close today. Prepare tomorrow. Recover."},
        {"id": "night_coach_02", "tone": "coach", "message": "Shutdown window. Review, reset, rest."},
    ],
}


SPECIAL_MESSAGE_TEMPLATES = {
    "birthday": {
        "id": "special_birthday_01",
        "message": "Happy birthday. What a year to be building something real.",
    },
    "new_year": {
        "id": "special_new_year_01",
        "message": "You didn't wait for today to start. You've been building since Day 1.",
    },
    "milestone": {
        "id": "special_milestone_01",
        "message": "You're halfway. The second half is where most people stop. You won't.",
    },
    "day_30": {
        "id": "special_day_30_01",
        "message": "A month ago you started with a goal. Today you have 30 days of proof.",
    },
    "day_21": {
        "id": "special_day_21_01",
        "message": "21 days. The habit is forming. You've done the hard part.",
    },
    "day_7": {
        "id": "special_day_7_01",
        "message": "Seven days. Most people don't make it here. You did.",
    },
    "missed_day": {
        "id": "special_missed_day_01",
        "message": "You're back. That's the move - not the miss.",
    },
    "monday": {
        "id": "special_monday_01",
        "message": "Clean slate. Everything you build this week compounds.",
    },
}


SPECIAL_PRIORITY = (
    "birthday",
    "new_year",
    "milestone",
    "day_30",
    "day_21",
    "day_7",
    "missed_day",
    "monday",
)


MESSAGE_TEMPLATES = {
    "wake": {
        "early": _tones(
            bro=[
                "Up before the world gets loud. That's how people pull ahead.",
                "You're early, bro. That's free momentum.",
                "Nice. You beat the clock today.",
            ],
            gentle=[
                "You're up early today. That's a lovely start.",
                "You gave yourself a soft head start this morning.",
                "Early wake-up. You're meeting the day with care.",
            ],
            soft_girl=[
                "You're up early, and it already feels a little magical.",
                "Such a pretty start to the day. You're ahead already.",
                "Early wake-ups look good on you.",
            ],
            coach=[
                "You're early. Keep the advantage.",
                "Early start. Maintain the lead.",
                "Ahead of schedule. Use it.",
            ],
        ),
        "on_time": _tones(
            bro=[
                "Right on time. Solid start, let's move.",
                "On schedule, bro. Clean work.",
                "You hit the mark this morning.",
            ],
            gentle=[
                "Right on time. Nice and steady.",
                "You're on schedule today. That's enough to build on.",
                "You woke up right when you meant to. Good job.",
            ],
            soft_girl=[
                "Right on time. Cute, calm, and ready.",
                "You landed exactly where you meant to this morning.",
                "On time and already doing better than yesterday-you feared.",
            ],
            coach=[
                "On time. Proceed.",
                "Schedule met. Keep moving.",
                "Target hit. Next step.",
            ],
        ),
        "late": _tones(
            bro=[
                "A little late, but the day is still yours if you claim it now.",
                "Not your sharpest wake-up, bro. Recover fast.",
                "You lost a little time. Don't lose the day with it.",
            ],
            gentle=[
                "A slower start today, and that's okay. Let's still make it count.",
                "You're a bit behind this morning, but you're not out of rhythm.",
                "Late start. Gentle reset, then begin.",
            ],
            soft_girl=[
                "A sleepy start, but the day still wants you in it.",
                "You're a little late, angel, not too late.",
                "Slow start, soft reset, still your day.",
            ],
            coach=[
                "Late start. Recover with focus.",
                "Behind schedule. Cut hesitation.",
                "You are late. Act immediately.",
            ],
        ),
    },
    "snooze": _tones(
        bro=[
            "Two snoozes in and the pillow is winning. Take the round back.",
            "Bro, enough negotiations with the alarm. Stand up.",
            "Snooze streak noted. Let's not make that your opener.",
        ],
        gentle=[
            "You've snoozed a couple of times. Let's ease up and get moving now.",
            "The bed made a strong case. You can still choose the day from here.",
            "A few snoozes happened. No shame, just begin now.",
        ],
        soft_girl=[
            "Okay sleepyhead, the snooze button had its moment. Now it's your turn.",
            "You've cuddled the morning enough. Come back to your life now.",
            "The bed was sweet, but the day still needs you, lovely.",
        ],
        coach=[
            "Snooze threshold reached. Stand up now.",
            "Too many snoozes. End delay.",
            "Snoozing is over. Start moving.",
        ],
    ),
    "streak": {
        3: _tones(
            bro="Three-day ritual streak. You're building proof now.",
            gentle="Three days in a row. Quiet consistency is growing.",
            soft_girl="Three little wins in a row. That's how momentum blooms.",
            coach="Three-day streak. Repeat the standard.",
        ),
        7: _tones(
            bro="Seven straight days. That's not luck anymore.",
            gentle="A full week of showing up. Beautiful work.",
            soft_girl="Seven days of staying with yourself. Love that.",
            coach="Seven-day streak. Keep the chain intact.",
        ),
        14: _tones(
            bro="Fourteen days. This is becoming your identity.",
            gentle="Two steady weeks. Your rhythm is becoming real.",
            soft_girl="Two whole weeks. You're becoming so dependable to yourself.",
            coach="Fourteen days. Consistency is compounding.",
        ),
        30: _tones(
            bro="Thirty days. That's a serious standard now.",
            gentle="Thirty days of care and follow-through. That's powerful.",
            soft_girl="Thirty days. You're glowing with discipline now.",
            coach="Thirty-day streak. This is the baseline now.",
        ),
    },
    "task": {
        "done": _tones(
            bro=[
                "Yesterday's task got done. That's the kind of carryover we want.",
                "You closed yesterday's one thing. Strong.",
                "Task finished yesterday. Stack another one.",
            ],
            gentle=[
                "You completed yesterday's task. That's a kind thing to do for today-you.",
                "Yesterday's one thing got done. Nice follow-through.",
                "You kept your promise yesterday. Bring that energy forward.",
            ],
            soft_girl=[
                "You did yesterday's task, and honestly, that's adorable discipline.",
                "Yesterday's one thing got done. Gold star energy.",
                "You kept the promise from last night. Sweet and strong.",
            ],
            coach=[
                "Yesterday's task: completed.",
                "Task done yesterday. Continue.",
                "Execution confirmed from yesterday.",
            ],
        ),
        "partial": _tones(
            bro=[
                "You got part of yesterday's task done. Better than a blank page, but finish cleaner today.",
                "Partial hit yesterday. Progress, not closure.",
                "You moved the ball yesterday. Today we finish stronger.",
            ],
            gentle=[
                "You made some progress yesterday. Let's turn that into completion today.",
                "Yesterday was partial, not wasted. Keep going.",
                "You touched the task yesterday. That's a start to build on.",
            ],
            soft_girl=[
                "You made a little progress yesterday, and that still counts, lovely.",
                "Partial progress is still progress. Let's keep the softness and the follow-through.",
                "You didn't finish yesterday, but you didn't disappear either.",
            ],
            coach=[
                "Yesterday was partial. Improve completion today.",
                "Partial execution yesterday. Tighten follow-through.",
                "Not complete. Still recoverable.",
            ],
        ),
        "missed": _tones(
            bro=[
                "Yesterday's task slipped. Fine. Today doesn't get the same excuse.",
                "Missed yesterday. Reset fast and hit today's one thing.",
                "You missed the task yesterday. Own it, then move.",
            ],
            gentle=[
                "Yesterday didn't land. Today is a fresh chance.",
                "You missed yesterday's task, and you still get to begin again.",
                "Yesterday was hard. Let's keep today's ask simple and real.",
            ],
            soft_girl=[
                "Yesterday got away from you. It happens. We try again beautifully today.",
                "You missed the task yesterday, but not your chance to come back.",
                "No shame for yesterday. Just a soft return today.",
            ],
            coach=[
                "Yesterday's task was missed. Reset immediately.",
                "Missed yesterday. Execute today.",
                "No completion yesterday. Correct today.",
            ],
        ),
    },
    "routine": {
        "water": _tones(
            bro="First move: water before excuses.",
            gentle="Start with a glass of water and let your body wake kindly.",
            soft_girl="Drink some water first, gorgeous.",
            coach="Hydrate first.",
        ),
        "coffee": _tones(
            bro="Coffee can wait one beat. Make it intentional.",
            gentle="If coffee helps, make it part of a calm start.",
            soft_girl="Make your coffee slowly and let it feel like a tiny ritual.",
            coach="Use coffee as a tool, not a delay.",
        ),
        "freshen": _tones(
            bro="Wash up and shake the sleep off.",
            gentle="Freshen up and let your body catch up with your intention.",
            soft_girl="Freshen up a little. It changes the whole mood.",
            coach="Freshen up and reset state.",
        ),
        "no_phone": _tones(
            bro="No phone scroll before your first move.",
            gentle="Give yourself a few phone-free minutes before the world enters.",
            soft_girl="Please don't hand your morning to your phone just yet.",
            coach="No phone before first task.",
        ),
        "stretch": _tones(
            bro="Give me one good stretch and get your blood moving.",
            gentle="Take a moment to stretch and wake your body softly.",
            soft_girl="Do one sweet little stretch before you start.",
            coach="Stretch once. Activate.",
        ),
    },
    "closer": _tones(
        bro=[
            "Let's make today obvious.",
            "Keep it simple and hit the one thing.",
            "Move before the mood changes.",
        ],
        gentle=[
            "Take the next step softly and clearly.",
            "You only need the next good action.",
            "Keep today small, clear, and kind.",
        ],
        soft_girl=[
            "Go make today lovely and real.",
            "One clear move, pretty focus, let's go.",
            "You're ready. Keep it soft and serious.",
        ],
        coach=[
            "Begin now.",
            "Execute the next action.",
            "Move into the day.",
        ],
    ),
    "night_open": _tones(
        bro=[
            "Night check-in, bro. Let's close the loop.",
            "End of day. Time to tell the truth and set tomorrow up.",
            "Let's cleanly land today and line up tomorrow.",
        ],
        gentle=[
            "Night check-in. Let's look at the day with honesty and care.",
            "Time to close the day gently and prepare the next one.",
            "Let's settle tonight well and make tomorrow lighter.",
        ],
        soft_girl=[
            "Night check-in, lovely. Let's tuck today in properly.",
            "Time for a soft little review of the day.",
            "Let's close the day sweetly and set up tomorrow.",
        ],
        coach=[
            "Night check-in. Review and reset.",
            "Close today. Prepare tomorrow.",
            "Review the day. Set the next move.",
        ],
    ),
    "night_task_done": _tones(
        bro=[
            "You got it done. That's how tomorrow gets easier.",
            "Task handled. Good. Lock in the next one.",
            "Done means done. Nice work.",
        ],
        gentle=[
            "You completed it today. That's a solid close.",
            "Well done. You carried today's promise through.",
            "That task got done. Let yourself feel that.",
        ],
        soft_girl=[
            "You did it today. Love that for you.",
            "Task complete. Very cute, very disciplined.",
            "You followed through today, and that matters.",
        ],
        coach=[
            "Task completed. Good.",
            "Execution confirmed.",
            "Completed. Set tomorrow.",
        ],
    ),
    "night_task_missed": _tones(
        bro=[
            "Not the finish we wanted, but the reset starts now.",
            "Missed it today. Fine. Tomorrow gets a cleaner plan.",
            "That one slipped. Own it and reset.",
        ],
        gentle=[
            "It didn't fully happen today. Let's make tomorrow simpler.",
            "Today was imperfect. Tomorrow still deserves a clear plan.",
            "You missed it today. We'll reset without drama.",
        ],
        soft_girl=[
            "It didn't happen today, but tomorrow can still be beautiful.",
            "Today got messy. We'll make tomorrow gentler and clearer.",
            "No spiral tonight. Just a softer plan for tomorrow.",
        ],
        coach=[
            "Missed today. Reset.",
            "Not completed. Adjust tomorrow.",
            "Execution missed. Re-plan now.",
        ],
    ),
    "night_intent_confirmed": _tones(
        bro="Locked. Tomorrow's move is {task}.",
        gentle="Okay. Tomorrow's one thing is {task}.",
        soft_girl="Perfect. Tomorrow's little mission is {task}.",
        coach="Confirmed: {task}.",
    ),
    "night_closer": _tones(
        bro="Day {day} wraps here. Alarm is set for {time}. Respect the plan.",
        gentle="Day {day} is closed. Morning alarm is set for {time}. Rest well.",
        soft_girl="Day {day} is tucked in. Morning alarm is set for {time}. Sleep sweet.",
        coach="Day {day} closed. Alarm set for {time}. Recover well.",
    ),
}


DATE_TEMPLATES = {
    "monday": _tones(
        bro=[
            "Monday. Set the tone before the week starts talking back.",
            "It's Monday. Strong start, clean week.",
            "Monday energy. Get ahead early.",
        ],
        gentle=[
            "It's Monday. A gentle start can still shape the whole week.",
            "New week, fresh page. Start kindly and clearly.",
            "Monday is here. Let's begin with intention.",
        ],
        soft_girl=[
            "It's Monday, babe. New week, fresh little chapter.",
            "Monday morning. Time to set the vibe for the week.",
            "A brand new week is here. Make it soft and strong.",
        ],
        coach=[
            "Monday. Establish the standard.",
            "Week start. Set pace.",
            "Monday. Lead the week.",
        ],
    ),
    "friday": _tones(
        bro=[
            "Friday. Finish strong so the weekend feels earned.",
            "It's Friday. Land the week properly.",
            "Friday is not coast day. Close hard.",
        ],
        gentle=[
            "Friday is here. Finish the week with care.",
            "It's Friday. One more steady push.",
            "End the week well and let yourself feel it.",
        ],
        soft_girl=[
            "Happy Friday. Let's make the closeout feel satisfying.",
            "Friday morning. One more pretty little effort.",
            "It's Friday. Finish well, then exhale.",
        ],
        coach=[
            "Friday. Close the week.",
            "End the week with execution.",
            "Friday. Finish strong.",
        ],
    ),
    "sunday": _tones(
        bro=[
            "Sunday. Reset day, not drift day.",
            "It's Sunday. Line up the week before it hits.",
            "Sunday is for reset and positioning.",
        ],
        gentle=[
            "Sunday is here. A calm reset goes a long way.",
            "It's Sunday. Let's make space and prepare well.",
            "Sunday can be soft and still intentional.",
        ],
        soft_girl=[
            "Sunday morning. Reset your little world.",
            "It's Sunday. Soft prep, clear heart, good week.",
            "Sunday is for cozy resets and real intention.",
        ],
        coach=[
            "Sunday. Reset and prepare.",
            "Use Sunday to position the week.",
            "Sunday. Plan, then recover.",
        ],
    ),
    "new_year": _tones(
        bro="New year. Fresh scoreboard.",
        gentle="A new year begins today. Start with care.",
        soft_girl="Happy New Year. New chapter, beautiful energy.",
        coach="New year. Set the baseline immediately.",
    ),
    "new_year_eve": _tones(
        bro="Last day of the year. Finish with intention.",
        gentle="Year-end today. Close it with honesty and warmth.",
        soft_girl="Last morning of the year. Make it count, lovely.",
        coach="Final day of the year. Finish clean.",
    ),
    "birthday": _tones(
        bro="Birthday energy. Show yourself what the next year gets.",
        gentle="Happy birthday. Let today reflect the person you're becoming.",
        soft_girl="Happy birthday, angel. Start your new year beautifully.",
        coach="Birthday. Mark it with action.",
    ),
    "winter": _tones(
        bro="Winter pace, steady fire.",
        gentle="Winter asks for a steady kind of discipline.",
        soft_girl="Winter morning. Cozy focus counts too.",
        coach="Winter. Keep consistency warm.",
    ),
    "summer": _tones(
        bro="Summer energy. Use the extra light.",
        gentle="Summer gives you room. Use it gently.",
        soft_girl="Summer mood. Bright day, clear intention.",
        coach="Summer. Convert energy into action.",
    ),
    "spring": _tones(
        bro="Spring reset. Build something fresh.",
        gentle="Spring is here. Let the reset be real.",
        soft_girl="Spring morning. Fresh start energy everywhere.",
        coach="Spring. Renew and execute.",
    ),
    "autumn": _tones(
        bro="Autumn energy. Tighten up and focus.",
        gentle="Autumn invites a quieter kind of discipline.",
        soft_girl="Autumn morning. Cozy focus looks good on you.",
        coach="Autumn. Refine and continue.",
    ),
}


MILESTONE_TEMPLATES = {
    "day_1": _tones(
        bro="Day 1. No legend talk, just first reps.",
        gentle="Day 1. The beginning matters because you showed up.",
        soft_girl="Day 1, lovely. Tiny start, real magic.",
        coach="Day 1. Start.",
    ),
    "day_7": _tones(
        bro="Day 7. One week of proof.",
        gentle="Day 7. A full week of effort is worth noticing.",
        soft_girl="Day 7. Your first little week is complete.",
        coach="Day 7. Sustain.",
    ),
    "day_14": _tones(
        bro="Day 14. Two weeks says this is getting real.",
        gentle="Day 14. Two weeks of showing up changes things.",
        soft_girl="Day 14. Two sweet, serious weeks.",
        coach="Day 14. Continue the standard.",
    ),
    "day_21": _tones(
        bro="Day 21. Habit territory now.",
        gentle="Day 21. The rhythm is becoming familiar now.",
        soft_girl="Day 21. You're settling into something beautiful.",
        coach="Day 21. Consolidate the habit.",
    ),
    "day_30": _tones(
        bro="Day 30. Thirty days earns respect.",
        gentle="Day 30. A month of effort is a real foundation.",
        soft_girl="Day 30. A whole month. So proud of you.",
        coach="Day 30. Foundation established.",
    ),
    "day_50": _tones(
        bro="Day 50. That's serious staying power.",
        gentle="Day 50. Fifty days says you're committed.",
        soft_girl="Day 50. Fifty soft, strong days.",
        coach="Day 50. Momentum is proven.",
    ),
    "day_100": _tones(
        bro="Day 100. Triple digits. That's elite follow-through.",
        gentle="Day 100. One hundred days of care and consistency.",
        soft_girl="Day 100. Triple digits, gorgeous.",
        coach="Day 100. Elite consistency.",
    ),
    "final_day": _tones(
        bro="Final stretch tomorrow. Tighten everything.",
        gentle="Tomorrow is the final day. Stay present and steady.",
        soft_girl="Tomorrow is the final day. One more beautiful push.",
        coach="Final day tomorrow. Stay sharp.",
    ),
    "goal_complete": _tones(
        bro="Completion day. Finish what you came here to do.",
        gentle="Completion day is here. Honor the work by finishing well.",
        soft_girl="Completion day, lovely. Bring it home.",
        coach="Completion day. Finish decisively.",
    ),
}


def get_milestone_key(day_number, total_days):
    if not day_number or not total_days:
        return None
    if day_number == total_days:
        return "goal_complete"
    if day_number == total_days - 1:
        return "final_day"
    milestone_map = {
        1: "day_1",
        7: "day_7",
        14: "day_14",
        21: "day_21",
        30: "day_30",
        50: "day_50",
        100: "day_100",
    }
    return milestone_map.get(day_number)
