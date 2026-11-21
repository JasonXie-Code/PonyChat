/* Credits describe this recording; catalog characters can also describe the work. */
(function () {
  "use strict";
  const names = (items) => [...new Set(items || [])];

  function get(song) {
    const reviewed = song.recordingCredits || {};
    const instrumental = song.instrumental === true || song.versionKind === "instrumental";
    const legacyRoles = song.versionKind === "demo" ? [] : song.characters;
    return {
      artist: reviewed.artist ?? song.artist ?? "",
      featured: names(reviewed.featuredArtists),
      vocals: instrumental ? [] : names(reviewed.vocals),
      characters: instrumental ? [] : names(reviewed.characters ?? legacyRoles),
      backing: instrumental ? [] : names(reviewed.backingVocals),
      backingCharacters: instrumental ? [] : names(reviewed.backingCharacters),
      spokenCharacters: instrumental ? [] : names(reviewed.spokenCharacters),
    };
  }

  const joined = (items) => items.join("、");
  function artistLine(credits) {
    return [credits.artist, credits.featured.length ? "feat. " + joined(credits.featured) : ""]
      .filter(Boolean).join(" ");
  }

  function compact(song) {
    const credits = get(song);
    return joined(credits.vocals) || artistLine(credits) || joined(credits.characters.slice(0, 2));
  }

  function mediaArtist(song) {
    const credits = get(song);
    return artistLine(credits) || joined(credits.vocals) || joined(credits.characters);
  }

  function detail(song) {
    const credits = get(song);
    const artist = artistLine(credits);
    const vocals = joined(credits.vocals);
    const backing = [joined(credits.backing), joined(credits.backingCharacters)]
      .filter(Boolean).join(" / ");
    return [
      vocals && "演唱：" + vocals,
      artist && artist !== vocals && "艺人：" + artist,
      credits.characters.length && "角色：" + joined(credits.characters),
      backing && "和声：" + backing,
      credits.spokenCharacters.length && "对白：" + joined(credits.spokenCharacters),
    ].filter(Boolean);
  }

  function searchTerms(song) {
    const {artist, featured, vocals, characters, backing, backingCharacters, spokenCharacters} = get(song);
    return [artist, ...featured, ...vocals, ...characters, ...backing, ...backingCharacters, ...spokenCharacters];
  }

  window.MusicRecordingCredits = {compact, mediaArtist, detail, searchTerms};

  // Use the player's callback contract without changing its signed core bytes.
  const player = window.MusicPlayer;
  const setCallbacks = player.setCallbacks;
  player.setCallbacks = function (callbacks) {
    setCallbacks({
      ...callbacks,
      onSong(song) {
        if (song) {
          document.querySelector("#playerSub").textContent =
            [compact(song), song.albumTitle].filter(Boolean).join(" · ");
          document.querySelector("#nowSubtitle").textContent =
            [song.alias, song.albumTitle, song.episode, ...detail(song)].filter(Boolean).join(" · ");
          if (navigator.mediaSession?.metadata) navigator.mediaSession.metadata.artist = mediaArtist(song);
        }
        callbacks.onSong?.(song);
      },
    });
  };
})();
