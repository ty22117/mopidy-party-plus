'use strict';

// TODO : add a mopidy service designed for angular, to avoid ugly $scope.$apply()...
angular.module('partyApp', [])
  .controller('MainController', function ($scope, $http) {

    // Scope variables
    $scope.message = [];
    $scope.tracks = [];
    $scope.tracksToLookup = [];
    $scope.maxTracksToLookup = 50; // Will be overwritten later by module config
    $scope.loading = true;
    $scope.maxSongLengthMS = 0; //0 No limit. May be overwritten by module config
    $scope.searching = false;
    $scope.searchingSources = [];
    $scope.ready = false;
    $scope.playlistUrl = '';
    $scope.currentState = {
      paused: false,
      length: 0,
      position: 0,
      volume: 100,
      track: {
        length: 0,
        name: 'Nothing playing, add some songs to get the party going!'
      }
    };
    $scope.sources_blacklist = ['cd', 'file']; // Will be overwritten later by module config
    $scope.sources_priority = ['local'];       // Will be overwritten later by module config
    $scope.prioritized_sources = [];
    $scope.isSliderDragging = false;

    // Get the max tracks to lookup at once from the 'max_results' config value in mopidy.conf
    $http.get('/party_plus/config?key=max_results').then(function success (response) {
      if (response.status == 200) {
        $scope.maxTracksToLookup = response.data;
      }
    }, null);

    // Get the max song length 'max_song_duration' config value in mopidy.conf (minutes)
    $http.get('/party_plus/config?key=max_song_duration').then(function success (response) {
      if (response.status == 200) {
        $scope.maxSongLengthMS = response.data * 60000;
      }
    }, null);

    // Get the source priority list
    $http.get('/party_plus/config?key=source_prio').then(function success (response) {
      if (response.status == 200) {
        $scope.sources_priority = [...data.matchAll(/\w+/g)].map(x => x[0]);
      }
    }, null);
    // Get the source blacklist
    $http.get('/party_plus/config?key=source_blacklist').then(function success (response) {
      if (response.status == 200) {
        $scope.sources_blacklist = [...data.matchAll(/\w+/g)].map(x => x[0]);
      }
    }, null);

    var mopidy = new Mopidy({
      'callingConvention': 'by-position-or-by-name'
    });

    mopidy.on('state:online', function () {
      mopidy.playback
        .getCurrentTrack()
        .then(function (track) {
          if (track)
            $scope.currentState.track = track;
          return mopidy.playback.getState();
        })
        .then(function (state) {
          $scope.currentState.paused = (state === 'paused');
          return mopidy.tracklist.getLength();
        })
        .then(function (length) {
          $scope.currentState.length = length;
          return mopidy.playback.getTimePosition();
        })
        .then(function (position) {
          if (position !== undefined && position !== null) {
            $scope.currentState.position = position;
          }
          return mopidy.mixer.getVolume();
        })
        .then(function (volume) {
          if (volume !== undefined && volume !== null) {
            $scope.currentState.volume = volume;
          }
        })
        .done(function () {
          $scope.ready = true;
          $scope.loading = false;
          $scope.searching = false;
          $scope.$apply();
          $scope.search();
        });

      /* Initialize available sources */
      mopidy.library.browse({ "uri": null }).done(
        function (uri_results){
          $scope.sources = uri_results.map(source => source.uri.split(":")[0]);
          $scope.prioritized_sources = getPrioritizedSources($scope.sources, $scope.sources_priority, $scope.sources_blacklist)
        }
      );

    });

    mopidy.on('event:playbackStateChanged', function (event) {
      $scope.currentState.paused = (event.new_state === 'paused');
      $scope.$apply();
    });

    mopidy.on('event:trackPlaybackStarted', function (event) {
      $scope.currentState.track = event.tl_track.track;
      $scope.currentState.position = 0;
      $scope.$apply();
    });

    mopidy.on('event:tracklistChanged', function () {
      mopidy.tracklist.getLength().done(function (length) {
        $scope.currentState.length = length;
        $scope.$apply();
      });
    });

    $scope.printDuration = function (track) {
      if (!track.length)
        return '';

      var _sum = parseInt(track.length / 1000);
      var _min = parseInt(_sum / 60);
      var _sec = _sum % 60;

      return '(' + _min + ':' + (_sec < 10 ? '0' + _sec : _sec) + ')';
    };

    $scope.printTime = function (ms) {
      if (!ms)
        return '0:00';

      var _sum = parseInt(ms / 1000);
      var _min = parseInt(_sum / 60);
      var _sec = _sum % 60;

      return _min + ':' + (_sec < 10 ? '0' + _sec : _sec);
    };

    $scope.search = function () {
      $scope.message = [];
      $scope.tracks = [];
      $scope.tracksToLookup = [];
      $scope.searchingSources = [];

      if (!$scope.searchField) {
        $scope.browse();
      } else {
        $scope.searchSourcesInOrder();
      }
    };

    $scope.browse = function () {
        mopidy.library.browse({
          'uri': 'local:directory'  //TODO: depend on source_prio
        }).done($scope.handleBrowseResult);
        return;
    }

    $scope.handleBrowseResult = function (res) {
      $scope.loading = false;
      $scope.searching = false;
      $scope.tracks = [];
      $scope.tracksToLookup = [];

      for (var i = 0; i < res.length; i++) {
        if (res[i].type == 'directory' && res[i].uri == 'local:directory?type=track') {
          mopidy.library.browse({
            'uri': res[i].uri
          }).done($scope.handleBrowseResult);
        } else if (res[i].type == 'track') {
          $scope.tracksToLookup.push(res[i].uri);
        }
      }

      if ($scope.tracksToLookup) {
        $scope.lookupOnePageOfTracks();
      }
    }

    $scope.lookupOnePageOfTracks = function () {
      mopidy.library.lookup({ 'uris': $scope.tracksToLookup.splice(0, $scope.maxTracksToLookup) }).done(function (tracklistResult) {
        Object.values(tracklistResult).map(function (singleTrackResult) { return singleTrackResult[0]; }).forEach($scope.addTrackResult);
      });
    };

    $scope.searchSourcesInOrder = function () {
      $scope.searchingSources = angular.copy($scope.prioritized_sources);
      $scope.searching = true;

      for (const src of $scope.prioritized_sources) {
        $scope.searchSources([src]);
      }
    }

    $scope.searchSources = function ($sourceList) {
      if($sourceList.length > 0) {
        mopidy.library.search({
          'query': {
            'any': [$scope.searchField]
          },
          'uris': $sourceList.map(source => source + ':')
        }).done($scope.handleSearchResult);
      }
    }

    $scope.handleSearchResult = function (res) {
      var _index = 0;
      var _found = true;
      const index = $scope.searchingSources.indexOf(getSource(res));
      if (index !== -1) {
        $scope.searchingSources.splice(index, 1);
      }
      for (var i = 0; i < res.length; i++) {
        if (res[i].tracks) {
          for (var j = 0; j < res[i].tracks.length; j++) {
            if (res[i].tracks[j]) {
              if ($scope.maxSongLengthMS <= 0 || res[i].tracks[j].length <= $scope.maxSongLengthMS) {
                $scope.addTrackResult(res[i].tracks[j]);
                _index++;
                if (_index >= $scope.maxTracksToLookup) {
                  break;
                }
              }
            }
          }
        }
        if (_index >= $scope.maxTracksToLookup) {
          break;
        }
      }
      if ($scope.searchingSources.length < 1) {
        $scope.searching = false;
      }
      $scope.$apply();
    };

    $scope.addTrackResult = function (track) {
      $scope.tracks.push(track);
      mopidy.tracklist.filter([{ 'uri': [track.uri] }]).done(
        function (matches) {
          if (matches.length) {
            for (var i = 0; i < $scope.tracks.length; i++) {
              if ($scope.tracks[i].uri == matches[0].track.uri)
                $scope.tracks[i].disabled = true;
            }
          }
          $scope.$apply();
        });
    };

    $scope.addTrack = function (track) {
      track.disabled = true;

      $http.post('/party_plus/add', track.uri).then(
        function success(response) {
          $scope.message = ['success', 'Queued: ' + track.name];
        },
        function error(response) {
          if (response.status === 409) {
            $scope.message = ['error', '' + response.data];
          } else {
            $scope.message = ['error', 'Code ' + response.status + ' - ' + response.data];
          }
        }
      );
    };

    $scope.addPlaylist = function () {
      if (!$scope.playlistUrl) {
        $scope.message = ['error', 'Please enter a playlist or album URL'];
        return;
      }

      var requestData = {
        url: $scope.playlistUrl,
        source: 'auto'
      };

      $http.post('/party_plus/playlist', JSON.stringify(requestData), {
        headers: {'Content-Type': 'application/json'}
      }).then(
        function success(response) {
          if (response.data && response.data.success) {
            $scope.message = ['success', response.data.message];
            $scope.playlistUrl = ''; // Clear input
          } else if (response.data && response.data.error) {
            $scope.message = ['error', response.data.error];
          } else {
            $scope.message = ['success', 'Playlist added successfully!'];
            $scope.playlistUrl = '';
          }
        },
        function error(response) {
          try {
            var errorMsg = response.data && response.data.error ? response.data.error : response.data;
            $scope.message = ['error', 'Error: ' + errorMsg];
          } catch (e) {
            $scope.message = ['error', 'Code ' + response.status + ' - Failed to add playlist'];
          }
        }
      );
    };

    $scope.nextTrack = function () {
      $http.get('/party_plus/vote').then(
        function success(response) {
          $scope.message = ['success', '' + response.data];
        },
        function error(response) {
          $scope.message = ['error', '' + response.data];
        }
      );
    };

    $scope.getTrackSource = function (track) {
      var sourceAsText = 'unknown';
      if (track.uri) {
        sourceAsText = track.uri.split(':', '1')[0];
      }

      return sourceAsText;
    };

    $scope.getFontAwesomeIcon = function (source) {
      var sources_with_fa_icon = ['bandcamp', 'mixcloud', 'pandora', 'soundcloud', 'spotify', 'youtube', 'tidal'];
      var css_class = 'fa fa-music';

      if (source == 'local') {
        css_class = 'fa fa-folder';
      } else if (sources_with_fa_icon.includes(source)) {
        css_class = 'fa-brands fa-' + source;
      }

      return css_class;
    };

    $scope.togglePause = function () {
      var _fn = $scope.currentState.paused ? mopidy.playback.resume : mopidy.playback.pause;
      _fn().done();
    };

    $scope.seekTrack = function () {
      mopidy.playback.seek({value: Math.floor($scope.currentState.position)}).done();
    };

    $scope.setVolume = function () {
      mopidy.mixer.setVolume({volume: Math.floor($scope.currentState.volume)}).done();
    };

    $scope.onSliderDown = function () {
      $scope.isSliderDragging = true;
    };

    $scope.onSliderUp = function () {
      $scope.isSliderDragging = false;
    };

    // Update playback position every 200ms
    var positionUpdateInterval = setInterval(function () {
      if ($scope.ready && !$scope.currentState.paused && !$scope.isSliderDragging) {
        mopidy.playback.getTimePosition().done(function (position) {
          if (position !== undefined && position !== null) {
            $scope.$apply(function () {
              $scope.currentState.position = position;
            });
          }
        });
      }
    }, 200);
  });

function getPrioritizedSources (availablesources, sourceprio, blacklist) {
    const blacklistSet = new Set(blacklist); //eliminate duplicates
    const availableSet = new Set(availablesources);
    const prioritized = sourceprio.filter(src => availableSet.has(src) && !blacklistSet.has(src));
    const remaining = availablesources.filter(src => !blacklistSet.has(src) && !prioritized.includes(src));
    return [...prioritized, ...remaining];
}

function findFirstUri (obj) {
  if (typeof obj !== 'object' || obj === null) return null;

  if ('uri' in obj && typeof obj.uri === 'string') {
    return obj.uri;
  }

  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      const found = findFirstUri(obj[key]);
      if (found) return found;
    }
  }

  return null;
}

function getSource (result) {
  var uri = findFirstUri(result);
  if (uri) {
    return uri.split(':', '1')[0];
  }
  return ""
}
