/*
	Bookmarklet code
	Must then be wrapped in:
	javascript:(function(){CODE})()
	(where CODE is the code below, MINIFIED)
	
	Using: https://minify-js.com/
*/

// send data to the clipboard
function copyJsonToClipboard(data)
{
	let listener = (event) => {
		event.preventDefault();
		event.clipboardData.setData("text/plain", JSON.stringify(data));
	};
	document.addEventListener("copy", listener);
	document.execCommand("copy");
	document.removeEventListener("copy", listener);
}

const hash = window.location.hash;
const BOOKMARK_VERSION = 3;

if(
	(
		hash.startsWith("#party/index/") ||
		hash.startsWith("#party/expectancy_damage/index") ||
		hash.startsWith("#tower/party/index/") ||
		(hash.startsWith("#event/sequenceraid") && hash.includes("/party/index/"))
	) &&
	!hash.startsWith("#tower/party/expectancy_damage/index/")
)
{
	// party screen
	let obj = {
		ver: BOOKMARK_VERSION,
		lang: Game.lang,
		party: Game.view.deck_model.attributes,
	};
	try {
		if(Game.view.expectancyDamageData && document.getElementsByClassName("txt-gauge-num").length > 0)
		{
			obj.party.calculator = [];
			for(const elem of document.getElementsByClassName("txt-gauge-num"))
			{
				obj.party.calculator.push(elem.textContent);
			}
			obj.party.support_summon = Game.view.expectancyDamageData.imageId;
			copyJsonToClipboard(obj);
		}
		else
		{
			alert("Open the estimate damage calculator and click the bookmark.")
		}
	} catch (error) {};
}
else if (
	hash.startsWith("#zenith/npc") ||
	hash.startsWith("#tower/zenith/npc") ||
	/^#event\/[a-zA-Z0-9]+\/zenith\/npc/.test(hash)
)
{
	// character emp screen
	let obj = {
		ver: BOOKMARK_VERSION,
		lang: Game.lang,
		id: parseInt(Game.view.npcId, 10),
		emp: Game.view.bonusListModel.attributes.bonus_list,
		ring: Game.view.npcaugmentData.param_data,
		domain: [],
		saint: [],
		extra: []
	};
	try {
		let domains = document.getElementById("prt-domain-evoker-list").getElementsByClassName("prt-bonus-detail");
		for (let i = 0; i < domains.length; ++i) {
			obj.domain.push([domains[i].children[0].className, domains[i].children[1].textContent, domains[i].children[2] ? domains[i].children[2].textContent : null]);
		}
		if (document.getElementById("prt-shisei-wrapper").getElementsByClassName("prt-progress-gauge").length > 0) {
			let saints = document.getElementById("prt-shisei-wrapper").getElementsByClassName("prt-progress-gauge")[0].getElementsByClassName("ico-progress-gauge");
			for (let i = 0; i < saints.length; ++i) {
				obj.saint.push([saints[i].className, null, null]);
			}
			saints = document.getElementById("prt-shisei-wrapper").getElementsByClassName("prt-bonus-detail");
			for (let i = 0; i < saints.length; ++i) {
				obj.saint.push([saints[i].children[0].className, saints[i].children[1].textContent, saints[i].children[2] ? saints[i].children[2].textContent : null]);
			}
		}
		if (document.getElementsByClassName("cnt-extra-lb extra numbers").length > 0) {
			let extras = document.getElementsByClassName("cnt-extra-lb extra numbers")[0].getElementsByClassName("prt-bonus-detail");
			for (let i = 0; i < extras.length; ++i) {
				obj.extra.push([extras[i].children[0].className, extras[i].children[1].textContent, extras[i].children[2] ? extras[i].children[2].textContent : null]);
			}
		}
		copyJsonToClipboard(obj);
	} catch (error) {};
}
else if (
	hash.startsWith("#list/detail_npc") ||
	hash.startsWith("#party/list/detail_npc") ||
	hash.startsWith("#party/top/detail_npc") ||
	hash.startsWith("#tower/list/detail_npc") ||
	hash.startsWith("#tower/party/top/detail_npc") ||
	/^#event\/[a-zA-Z0-9]+\/list\/detail_npc/.test(hash)
)
{
	// character detail screen (for artifacts)
	let obj = {
		ver: BOOKMARK_VERSION,
		lang: Game.lang,
		id: parseInt(Game.view.npcId, 10),
		artifact: {}
	};
	try {
		let af = document.getElementsByClassName("artifact-body");
		if (af.length > 0) {
			let img = af[0].getElementsByClassName("img-icon-body")[0].src;
			let skills = [];
			let elems = af[0].getElementsByClassName("prt-artifact-skill-item");
			for (let i = 0; i < elems.length; ++i) {
				skills.push({
					lvl: elems[i].getElementsByClassName("artifact-skill-level")[0].textContent,
					icon: elems[i].getElementsByClassName("artifact-score-icon")[0].getElementsByTagName("img")[0].src,
					desc: elems[i].getElementsByClassName("artifact-skill-desc")[0].textContent,
					value: elems[i].getElementsByClassName("artifact-skill-value")[0].textContent
				});
			}
			obj.artifact = {
				img: img,
				skills: skills
			};
		}
		copyJsonToClipboard(obj);
	} catch (error) {};
}
else
{
	try
	{
		let obj = {ver: BOOKMARK_VERSION};
		if(stage.pJsnData.is_boss != null)
		{
			obj.id = stage.pJsnData.is_boss.split("_").slice(2).join("_");
		}
		else
		{
			obj.id = sstage.pJsnData.boss.param[0].cjs.split("_")[1];
		}
		obj.background = stage.pJsnData.background.split("/")[4].split(".")[0];
		obj.icon = stage.pJsnData.boss.param[0].cjs.split("_")[1];
		copyJsonToClipboard(obj);
	} catch (error) {
		alert("Use this bookmark on a compatible page.")
	};
}